"""A service is a process that talks to JupyterHub.
Types of services:
    Managed:
      - managed by JupyterHub (always subprocess, no custom Spawners)
      - always a long-running process
      - managed services are restarted automatically if they exit unexpectedly
    Unmanaged:
      - managed by external service (docker, systemd, etc.)
      - do not need to be long-running processes, or processes at all
URL: needs a route added to the proxy.
  - Public route will always be /services/service-name
  - url specified in config
  - if port is 0, Hub will select a port
API access:
  - admin: tokens will have admin-access to the API
  - not admin: tokens will only have non-admin access
    (not much they can do other than defer to Hub for auth)
An externally managed service running on a URL::
    {
        'name': 'my-service',
        'url': 'https://host:8888',
        'admin': True,
        'api_token': 'super-secret',
    }
A hub-managed service with no URL::
    {
        'name': 'cull-idle',
        'command': ['python', '/path/to/cull-idle']
        'admin': True,
    }
"""
import asyncio
import copy
import os
import pipes
import shutil
from subprocess import Popen

from traitlets import Any
from traitlets import Bool
from traitlets import default
from traitlets import Dict
from traitlets import HasTraits
from traitlets import Instance
from traitlets import List
from traitlets import Unicode
from traitlets import validate
from traitlets.config import LoggingConfigurable

from .. import orm
from ..objects import Server
from ..spawner import LocalProcessSpawner
from ..spawner import set_user_setuid
from ..traitlets import Command
from ..utils import url_path_join


class _MockUser(HasTraits):
    name = Unicode()
    server = Instance(orm.Server, allow_none=True)
    state = Dict()
    service = Instance(__name__ + '.Service')
    host = Unicode()

    @property
    def url(self):
        if not self.server:
            return ''
        if self.host:
            return self.host + self.server.base_url
        else:
            return self.server.base_url

    @property
    def base_url(self):
        if not self.server:
            return ''
        return self.server.base_url


# We probably shouldn't use a Spawner here,
# but there are too many concepts to share.


class _ServiceSpawner(LocalProcessSpawner):
    """Subclass of LocalProcessSpawner
    Removes notebook-specific-ness from LocalProcessSpawner.
    """

    cwd = Unicode()
    cmd = Command(minlen=0)
    _service_name = Unicode()

    @default("oauth_scopes")
    def _default_oauth_scopes(self):
        return [
            "access:services",
            f"access:services!service={self._service_name}",
        ]

    def make_preexec_fn(self, name):
        if not name:
            # no setuid if no name
            return
        return set_user_setuid(name, chdir=False)

    def user_env(self, env):
        if not self.user.name:
            return env
        else:
            return super().user_env(env)
