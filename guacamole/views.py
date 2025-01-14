# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import threading
import uuid
import re

from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from guacamole.client import GuacamoleClient

logger = logging.getLogger(__name__)
sockets = {}
sockets_lock = threading.RLock()
read_lock = threading.RLock()
write_lock = threading.RLock()
pending_read_request = threading.Event()


def index(request):
    return render(request, 'index.html', {})

def isValidURL(str):
 
    # Regex to check valid URL
    regex = ("[a-zA-Z0-9@:%._\\+~#?&//=]" +
             "{2,256}\\.[a-z]" +
             "{2,6}\\b([-a-zA-Z0-9@:%" +
             "._\\+~#?&//=]*)")
     
    # Compile the ReGex
    p = re.compile(regex)
 
    # If the string is empty
    # return false
    if (str == None):
        return False
 
    # Return if the string
    # matched the ReGex
    if(re.search(p, str)):
        return True
    else:
        return False

@csrf_exempt
def tunnel(request):
    qs = request.META['QUERY_STRING']
    
    #if isValidURL(qs):
        #logger.info('tunnel %s', qs)
    if qs == 'connect':
        logger.info('tunnel %s', qs)
        return _do_connect(request)
    else:
        tokens = qs.split(':')
        
        if len(tokens) >= 2:
            if tokens[0] == 'read':
                logger.info('tunnel %s', qs)
                return _do_read(request, tokens[1])
            elif tokens[0] == 'write':
                logger.info('tunnel %s', qs)
                return _do_write(request, tokens[1])

    return HttpResponse(status=400)


def _do_connect(request):
    # Connect to guacd daemon
    client = GuacamoleClient(settings.GUACD_HOST, settings.GUACD_PORT)
    client.handshake(protocol='rdp',
                     hostname=settings.SSH_HOST,
                     port=settings.SSH_PORT,
                     username=settings.SSH_USER,
                     password=settings.SSH_PASSWORD)
                     #security='any',)

    cache_key = str(uuid.uuid4())
    with sockets_lock:
        logger.info('Saving socket with key %s', cache_key)
        sockets[cache_key] = client

    response = HttpResponse(content=cache_key)
    response['Cache-Control'] = 'no-cache'

    return response


def _do_read(request, cache_key):
    pending_read_request.set()

    def content():
        with sockets_lock:
            client = sockets[cache_key]

        with read_lock:
            pending_read_request.clear()

            while True:
                instruction = client.receive()
                if instruction:
                    yield instruction
                else:
                    break

                if pending_read_request.is_set():
                    logger.info('Letting another request take over.')
                    break

            # End-of-instruction marker
            yield '0.;'

    response = StreamingHttpResponse(content(),
                                     content_type='application/octet-stream')
    response['Cache-Control'] = 'no-cache'
    return response


def _do_write(request, cache_key):
    with sockets_lock:
        client = sockets[cache_key]

    with write_lock:
        while True:
            chunk = request.read(8192)
            if chunk:
                client.send(chunk)
            else:
                break

    response = HttpResponse(content_type='application/octet-stream')
    response['Cache-Control'] = 'no-cache'
    return response
