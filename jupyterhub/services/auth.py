"""Authenticating services with JupyterHub.
Tokens are sent to the Hub for verification.
The Hub replies with a JSON model describing the authenticated user.
``HubAuth`` can be used in any application, even outside tornado.
``HubAuthenticated`` is a mixin class for tornado handlers that should
authenticate with the Hub.
"""
import base64
import hashlib
import json
import os
import random
import re
import socket
import string
import time
import uuid
import warnings
from unittest import mock
from urllib.parse import urlencode

import requests
from tornado.httputil import url_concat
from tornado.log import app_log
from tornado.web import HTTPError
from tornado.web import RequestHandler
from traitlets import default
from traitlets import Dict
from traitlets import Instance
from traitlets import Integer
from traitlets import observe
from traitlets import Set
from traitlets import Unicode
from traitlets import validate
from traitlets.config import SingletonConfigurable

from ..scopes import _intersect_expanded_scopes
from ..utils import url_path_join


def check_scopes(required_scopes, scopes):
    """Check that required_scope(s) are in scopes
    Returns the subset of scopes matching required_scopes,
    which is truthy if any scopes match any required scopes.
    Correctly resolves scope filters *except* for groups -> user,
    e.g. require: access:server!user=x, have: access:server!group=y
    will not grant access to user x even if user x is in group y.
    Parameters
    ----------
    required_scopes: set
        The set of scopes required.
    scopes: set
        The set (or list) of scopes to check against required_scopes
    Returns
    -------
    relevant_scopes: set
        The set of scopes in required_scopes that are present in scopes,
        which is truthy if any required scopes are present,
        and falsy otherwise.
    """
    if isinstance(required_scopes, str):
        required_scopes = {required_scopes}

    intersection = _intersect_expanded_scopes(required_scopes, scopes)
    # re-intersect with required_scopes in case the intersection
    # applies stricter filters than required_scopes declares
    # e.g. required_scopes = {'read:users'} and intersection has only {'read:users!user=x'}
    return set(required_scopes) & intersection


class _ExpiringDict(dict):
    """Dict-like cache for Hub API requests
    Values will expire after max_age seconds.
    A monotonic timer is used (time.monotonic).
    A max_age of 0 means cache forever.
    """

    max_age = 0

    def __init__(self, max_age=0):
        self.max_age = max_age
        self.timestamps = {}
        self.values = {}

    def __setitem__(self, key, value):
        """Store key and record timestamp"""
        self.timestamps[key] = time.monotonic()
        self.values[key] = value

    def __repr__(self):
        """include values and timestamps in repr"""
        now = time.monotonic()
        return repr(
            {
                key: '{value} (age={age:.0f}s)'.format(
                    value=repr(value)[:16] + '...', age=now - self.timestamps[key]
                )
                for key, value in self.values.items()
            }
        )

    def _check_age(self, key):
        """Check timestamp for a key"""
        if key not in self.values:
            # not registered, nothing to do
            return
        now = time.monotonic()
        timestamp = self.timestamps[key]
        if self.max_age > 0 and timestamp + self.max_age < now:
            self.values.pop(key)
            self.timestamps.pop(key)

    def __contains__(self, key):
        """dict check for `key in dict`"""
        self._check_age(key)
        return key in self.values

    def __getitem__(self, key):
        """Check age before returning value"""
        self._check_age(key)
        return self.values[key]

    def get(self, key, default=None):
        """dict-like get:"""
        try:
            return self[key]
        except KeyError:
            return default

    def clear(self):
        """Clear the cache"""
        self.values.clear()
        self.timestamps.clear()


class HubAuth(SingletonConfigurable):
    """A class for authenticating with JupyterHub
    This can be used by any application.
    Use this base class only for direct, token-authenticated applications
    (web APIs).
    For applications that support direct visits from browsers,
    use HubOAuth to enable OAuth redirect-based authentication.
    If using tornado, use via :class:`HubAuthenticated` mixin.
    If using manually, use the ``.user_for_token(token_value)`` method
    to identify the user owning a given token.
    The following config must be set:
    - api_token (token for authenticating with JupyterHub API),
      fetched from the JUPYTERHUB_API_TOKEN env by default.
    The following config MAY be set:
    - api_url: the base URL of the Hub's internal API,
      fetched from JUPYTERHUB_API_URL by default.
    - cookie_cache_max_age: the number of seconds responses
      from the Hub should be cached.
    - login_url (the *public* ``/hub/login`` URL of the Hub).
    """

    hub_host = Unicode(
        '',
        help="""The public host of JupyterHub
        Only used if JupyterHub is spreading servers across subdomains.
        """,
    ).tag(config=True)

    @default('hub_host')
    def _default_hub_host(self):
        return os.getenv('JUPYTERHUB_HOST', '')

    base_url = Unicode(
        os.getenv('JUPYTERHUB_SERVICE_PREFIX') or '/',
        help="""The base URL prefix of this application
        e.g. /services/service-name/ or /user/name/
        Default: get from JUPYTERHUB_SERVICE_PREFIX
        """,
    ).tag(config=True)

    @validate('base_url')
    def _add_slash(self, proposal):
        """Ensure base_url starts and ends with /"""
        value = proposal['value']
        if not value.startswith('/'):
            value = '/' + value
        if not value.endswith('/'):
            value = value + '/'
        return value

    # where is the hub
    api_url = Unicode(
        os.getenv('JUPYTERHUB_API_URL') or 'http://127.0.0.1:8081/hub/api',
        help="""The base API URL of the Hub.
        Typically `http://hub-ip:hub-port/hub/api`
        """,
    ).tag(config=True)

    @default('api_url')
    def _api_url(self):
        env_url = os.getenv('JUPYTERHUB_API_URL')
        if env_url:
            return env_url
        else:
            return 'http://127.0.0.1:8081' + url_path_join(self.hub_prefix, 'api')

    api_token = Unicode(
        os.getenv('JUPYTERHUB_API_TOKEN', ''),
        help="""API key for accessing Hub API.
        Generate with `jupyterhub token [username]` or add to JupyterHub.services config.
        """,
    ).tag(config=True)

    hub_prefix = Unicode(
        '/hub/',
        help="""The URL prefix for the Hub itself.
        Typically /hub/
        """,
    ).tag(config=True)

    @default('hub_prefix')
    def _default_hub_prefix(self):
        return url_path_join(os.getenv('JUPYTERHUB_BASE_URL') or '/', 'hub') + '/'

    login_url = Unicode(
        '/hub/login',
        help="""The login URL to use
        Typically /hub/login
        """,
    ).tag(config=True)

    @default('login_url')
    def _default_login_url(self):
        return self.hub_host + url_path_join(self.hub_prefix, 'login')

    keyfile = Unicode(
        os.getenv('JUPYTERHUB_SSL_KEYFILE', ''),
        help="""The ssl key to use for requests
        Use with certfile
        """,
    ).tag(config=True)

    certfile = Unicode(
        os.getenv('JUPYTERHUB_SSL_CERTFILE', ''),
        help="""The ssl cert to use for requests
        Use with keyfile
        """,
    ).tag(config=True)

    client_ca = Unicode(
        os.getenv('JUPYTERHUB_SSL_CLIENT_CA', ''),
        help="""The ssl certificate authority to use to verify requests
        Use with keyfile and certfile
        """,
    ).tag(config=True)

    cookie_options = Dict(
        help="""Additional options to pass when setting cookies.
        Can include things like `expires_days=None` for session-expiry
        or `secure=True` if served on HTTPS and default HTTPS discovery fails
        (e.g. behind some proxies).
        """
    ).tag(config=True)

    @default('cookie_options')
    def _default_cookie_options(self):
        # load default from env
        options_env = os.environ.get('JUPYTERHUB_COOKIE_OPTIONS')
        if options_env:
            return json.loads(options_env)
        else:
            return {}

    cookie_cache_max_age = Integer(help="DEPRECATED. Use cache_max_age")

    @observe('cookie_cache_max_age')
    def _deprecated_cookie_cache(self, change):
        warnings.warn(
            "cookie_cache_max_age is deprecated in JupyterHub 0.8. Use cache_max_age instead."
        )
        self.cache_max_age = change.new

    cache_max_age = Integer(
        300,
        help="""The maximum time (in seconds) to cache the Hub's responses for authentication.
        A larger value reduces load on the Hub and occasional response lag.
        A smaller value reduces propagation time of changes on the Hub (rare).
        Default: 300 (five minutes)
        """,
    ).tag(config=True)
    cache = Instance(_ExpiringDict, allow_none=False)

    @default('cache')
    def _default_cache(self):
        return _ExpiringDict(self.cache_max_age)

    oauth_scopes = Set(
        Unicode(),
        help="""OAuth scopes to use for allowing access.
        Get from $JUPYTERHUB_OAUTH_SCOPES by default.
        """,
    ).tag(config=True)

    @default('oauth_scopes')
    def _default_scopes(self):
        env_scopes = os.getenv('JUPYTERHUB_OAUTH_SCOPES')
        if env_scopes:
            return set(json.loads(env_scopes))
        service_name = os.getenv("JUPYTERHUB_SERVICE_NAME")
        if service_name:
            return {f'access:services!service={service_name}'}
        return set()
    def _check_hub_authorization(self, url, api_token, cache_key=None, use_cache=True):
        """Identify a user with the Hub
        Args:
            url (str): The API URL to check the Hub for authorization
                       (e.g. http://127.0.0.1:8081/hub/api/user)
            cache_key (str): The key for checking the cache
            use_cache (bool): Specify use_cache=False to skip cached cookie values (default: True)
        Returns:
            user_model (dict): The user model, if a user is identified, None if authentication fails.
        Raises an HTTPError if the request failed for a reason other than no such user.
        """
        if use_cache:
            if cache_key is None:
                raise ValueError("cache_key is required when using cache")
            # check for a cached reply, so we don't check with the Hub if we don't have to
            try:
                return self.cache[cache_key]
            except KeyError:
                app_log.debug("HubAuth cache miss: %s", cache_key)

        data = self._api_request(
            'GET',
            url,
            headers={"Authorization": "token " + api_token},
            allow_403=True,
        )
        if data is None:
            app_log.warning("No Hub user identified for request")
        else:
            app_log.debug("Received request from Hub user %s", data)
        if use_cache:
            # cache result
            self.cache[cache_key] = data
        return data

    def _api_request(self, method, url, **kwargs):
        """Make an API request"""
        allow_403 = kwargs.pop('allow_403', False)
        headers = kwargs.setdefault('headers', {})
        headers.setdefault('Authorization', 'token %s' % self.api_token)
        if "cert" not in kwargs and self.certfile and self.keyfile:
            kwargs["cert"] = (self.certfile, self.keyfile)
            if self.client_ca:
                kwargs["verify"] = self.client_ca
        try:
            r = requests.request(method, url, **kwargs)
        except requests.ConnectionError as e:
            app_log.error("Error connecting to %s: %s", self.api_url, e)
            msg = "Failed to connect to Hub API at %r." % self.api_url
            msg += (
                "  Is the Hub accessible at this URL (from host: %s)?"
                % socket.gethostname()
            )
            if '127.0.0.1' in self.api_url:
                msg += (
                    "  Make sure to set c.JupyterHub.hub_ip to an IP accessible to"
                    + " single-user servers if the servers are not on the same host as the Hub."
                )
            raise HTTPError(500, msg)

        data = None
        if r.status_code == 403 and allow_403:
            pass
        elif r.status_code == 403:
            app_log.error(
                "I don't have permission to check authorization with JupyterHub, my auth token may have expired: [%i] %s",
                r.status_code,
                r.reason,
            )
            app_log.error(r.text)
            raise HTTPError(
                500, "Permission failure checking authorization, I may need a new token"
            )
        elif r.status_code >= 500:
            app_log.error(
                "Upstream failure verifying auth token: [%i] %s",
                r.status_code,
                r.reason,
            )
            app_log.error(r.text)
            raise HTTPError(502, "Failed to check authorization (upstream problem)")
        elif r.status_code >= 400:
            app_log.warning(
                "Failed to check authorization: [%i] %s", r.status_code, r.reason
            )
            app_log.warning(r.text)
            msg = "Failed to check authorization"
            # pass on error from oauth failure
            try:
                response = r.json()
                # prefer more specific 'error_description', fallback to 'error'
                description = response.get(
                    "error_description", response.get("error", "Unknown error")
                )
            except Exception:
                pass
            else:
                msg += ": " + description
            raise HTTPError(500, msg)
        else:
            data = r.json()

        return data
