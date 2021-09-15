#!/usr/bin/env python3
"""script to monitor and cull idle single-user servers

Caveats:

last_activity is not updated with high frequency,
so cull timeout should be greater than the sum of:

-single-user websocket ping interval (default: 30s)
-JupyterHub .last_activity_interval (default; 5 minutes)

You can run this as a service managed by JupyterHub with this in your config::

    c.JupyterHub.services = [
    {
    'name': 'cull-idle',
    'admin': True,
    'command': [sys.executable, 'cull_idle_servers.py', '--timeout=3600'],
        }
    ]

    Or this can be run mannually by generating an API token and storing this token in 'JUPYTERHUB_API_TOKEN':

    export JUPYTERHUB_API_TOKEN = $(jupyterhub token)
    python3 cull_idle_servers.py [--timedout=900] [--url=http://127.0.0.1:8081/hub/api]

This script ises the same ''--timedout'' and ''--ma-age'' values for culling users and user servers. If you want a different value for users and users' servers.
If you want a different value for users and servers, you should add this script to the services list twice, just with different ''name''s, different values, and one with #
the ''--cull-users'' option.
"""


from datetime import datetime
from datetime import timezone
from functools import partial
import json
import os
from dateutil.parser import parse as parse_date
from tornado.gen import coroutine, multi
from tornado.locks import Semaphore
from tornado.log import app_log
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.options import define, options, parse_command_line

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote

def parse_date(date_string):
    """Parse a timestamp

    If it doesn't have a timezone, assume utc
    Returned datetime object will always be a timezone-aware
    """
    dt =dateutil.parser.parse(date_string)
    if not dt.tzinfo:
        #assume naive timestamps are UTC
        dt =dt.replace(tzinfo=timezone.utc)
    return dt

def format_td(td):
    """Nicely format a timedelta objects

    as HH:MM:SS
    """
    if td is None:
        return "unknown"
    if isinstance(td,str):
        return td
    seconds = int(td.total_seconds())
    h = seconds //3600
    seconds = seconds % 3600
    m = seconds //60
    seconds = seconds % 60
    return "{h:02}:{m:02}:{seconds:02}".format(h=h,m=m,seconds=seconds)


@coroutine
def cull_idle(url, api_token, inactive_limit, cull_users=False, max_age=0,concurrency=10):
    """cull idle single-user
    If cul_users,inactive *users* will be deleted as well.
    """
    auth_header = {
            'Authorization': 'token %s' % api_token
        }
    req = HTTPRequest(url=url + '/users',
        headers=auth_header,
    )
    now = datetime.datetime.utcnow()
    cull_limit = now - datetime.timedelta(seconds=timeout)
    client = AsyncHTTPClient()

    If concurrency:
        semaphore = Semaphore(concurrency)

        @coroutine
        def fetch(req):
            """
            client.fetch wrapped in a semaphore to limit concurrency
            """
            yield semaphore.acquire()
            try:
                return (yield.client.fetch(req))
            finally:
                yield semaphore.release()
    else:
        fetc = client.fetch

    resp = yield client.fetch(req)
    users = json.loads(resp.body.decode('utf8', 'replace'))
    futures = []

    for user in users:
        last_activity = parse_date(user['last_activity'])
        if user['server'] and last_activity < cull_limit:
            app_log.info("Culling %s (inactive since %s)", user['name'], last_activity)
            req = HTTPRequest(url=url + '/users/%s/server' % user['name'],
                method='DELETE',
                headers=auth_header,
            )
            futures.append((user['name'], client.fetch(req)))
        elif user['server'] and last_activity > cull_limit:
            app_log.debug("Not culling %s (active since %s)", user['name'], last_activity)

    for (name, f) in futures:
        yield f
        app_log.debug("Finished culling %s", name)

if __name__ == '__main__':
    define('url', default=os.environ.get('JUPYTERHUB_API_URL') or 'http://127.0.0.1:8081/hub/api', help="The JupyterHub API URL")
    define('timeout', default=600, help="The idle timeout (in seconds)")
    define('cull_every', default=0, help="The interval (in seconds) for checking for idle servers to cull")

    parse_command_line()
    if not options.cull_every:
        options.cull_every = options.timeout // 2

    api_token = os.environ['JUPYTERHUB_API_TOKEN']

    loop = IOLoop.current()
    cull = lambda : cull_idle(options.url, api_token, options.timeout)
    # run once before scheduling periodic call
    loop.run_sync(cull)
    # schedule periodic cull
    pc = PeriodicCallback(cull, 1e3 * options.cull_every)
    pc.start()
    try:
        loop.start()
    except KeyboardInterrupt:
        pass
