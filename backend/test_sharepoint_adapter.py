import httpx
import pytest
from sharepoint_adapter import SharePointMetadata,SharePointUnavailable
SITE='https://exampletenant.sharepoint.com/sites/Operations'
def adapter(handler,token='test-only-placeholder'):
    return SharePointMetadata(SITE,'drive-demo','root-demo',lambda:token,httpx.Client(transport=httpx.MockTransport(handler)))
def test_missing_token_fails_without_network():
    calls=[]
    a=adapter(lambda r:calls.append(r),'')
    with pytest.raises(SharePointUnavailable):a.verify_site()
    assert calls==[]
@pytest.mark.parametrize('url',['http://exampletenant.sharepoint.com/sites/Operations','https://evil.example/sites/Operations','https://exampletenant.sharepoint.com/sites/Operations?token=secret','https://exampletenant.sharepoint.com/sites/Operations/../Other'])
def test_noncanonical_targets_rejected(url):
    with pytest.raises(ValueError):SharePointMetadata(url,'drive','root',lambda:'test')
def test_site_and_root_are_scoped_and_download_urls_not_exported():
    def handle(r):
        assert r.url.host=='graph.microsoft.com'
        if '/sites/' in r.url.path:return httpx.Response(200,json={'id':'site-demo','webUrl':SITE})
        if r.url.path.endswith('/children'):return httpx.Response(200,json={'value':[{'id':'file-demo','name':'fictitious.txt','size':1,'@microsoft.graph.downloadUrl':'do-not-export'}],'@odata.nextLink':'https://evil.example'})
        return httpx.Response(200,json={'id':'root-demo','folder':{},'webUrl':SITE+'/Shared Documents/PAGDOC'})
    a=adapter(handle);assert a.verify_site()['verified'];result=a.list_root();assert result['has_more'];assert 'downloadUrl' not in str(result)
def test_wrong_site_and_upstream_failure_fail_closed():
    with pytest.raises(SharePointUnavailable):adapter(lambda r:httpx.Response(403)).verify_site()
    with pytest.raises(SharePointUnavailable):adapter(lambda r:httpx.Response(200,json={'webUrl':'https://evil.example'})).verify_site()
