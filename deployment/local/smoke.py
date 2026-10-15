"""Host-side HTTPS verification against the local private pilot, using fictional CI data."""
import json
import ssl
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

context=ssl.create_default_context(cafile=sys.argv[1])
origin='https://localhost:8443'
with urlopen(origin+'/ready',context=context,timeout=15) as response:
    assert json.load(response)=={'status':'ready'}
with urlopen(origin+'/app',context=context,timeout=15) as response:
    html=response.read().decode()
    assert 'data-runtime="private"' in html and 'data-runtime="demo"' not in html
    assert '/app/assets/operations.js' in html
try:
    urlopen(origin+'/ops/bootstrap',context=context,timeout=15)
    raise AssertionError('Unauthenticated request was accepted')
except HTTPError as error:
    assert error.code==401
request=Request(origin+'/auth/login',data=json.dumps({'email':'private-pilot@example.invalid','password':'ci-only-private-pilot-password'}).encode(),headers={'Content-Type':'application/json'},method='POST')
with urlopen(request,context=context,timeout=15) as response:
    cookies=response.headers.get_all('Set-Cookie')
    assert cookies and any('Secure' in cookie and 'HttpOnly' in cookie for cookie in cookies)
    cookie_header='; '.join(cookie.split(';',1)[0] for cookie in cookies)
with urlopen(Request(origin+'/ops/bootstrap',headers={'Cookie':cookie_header}),context=context,timeout=15) as response:
    payload=json.load(response)
    assert payload['me']['email']=='private-pilot@example.invalid'
    assert payload['tenant']['name']=='Fictitious private CI tenant'
with urlopen(Request(origin+'/ops/integrations',headers={'Cookie':cookie_header}),context=context,timeout=15) as response:
    assert json.load(response)['storage']['binary_http_enabled'] is False
print('HTTPS, private UI, authentication boundary, secure session and disabled file transfer verified.')
