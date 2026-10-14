"""Read-only Graph metadata adapter for a future private SharePoint binding.

The ChatGPT connector's delegated account is NOT the application's runtime
credential. A server-side token provider and explicit site/drive/root binding are
required. This module never exports download URLs or tokens to clients.
"""
import re
from urllib.parse import quote,urlparse
import httpx

class SharePointUnavailable(RuntimeError):pass

class SharePointMetadata:
    def __init__(self,site_url,drive_id,root_id,token_provider,client=None):
        parsed=urlparse(site_url)
        if parsed.scheme!='https' or not re.fullmatch(r'[a-zA-Z0-9-]+\.sharepoint\.com',parsed.hostname or '') or parsed.username or parsed.password or parsed.query or parsed.fragment or not re.fullmatch(r'/sites/[A-Za-z0-9_-]+/?',parsed.path):
            raise ValueError('Use a canonical HTTPS SharePoint site URL')
        for identity in (drive_id,root_id):
            if not re.fullmatch(r'[A-Za-z0-9!_,.\-]{1,256}',identity or ''):raise ValueError('Invalid SharePoint binding')
        self.site_url=site_url.rstrip('/');self.drive_id=drive_id;self.root_id=root_id;self.token_provider=token_provider
        self.client=client or httpx.Client(timeout=15,follow_redirects=False)

    def _get(self,path):
        token=self.token_provider()
        if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise SharePointUnavailable('Private Microsoft identity is not configured')
        try:
            response=self.client.get('https://graph.microsoft.com/v1.0/'+path,headers={'Authorization':'Bearer '+token,'Accept':'application/json'},follow_redirects=False)
            if response.status_code!=200:raise SharePointUnavailable('SharePoint authorization or availability check failed')
            value=response.json()
            if not isinstance(value,dict):raise SharePointUnavailable('Invalid SharePoint response')
            return value
        except (httpx.HTTPError,ValueError) as exc:raise SharePointUnavailable('SharePoint unavailable') from exc

    def verify_site(self):
        parsed=urlparse(self.site_url)
        value=self._get('sites/'+parsed.hostname+':'+quote(parsed.path,safe='/'))
        if value.get('webUrl','').rstrip('/').lower()!=self.site_url.lower():raise SharePointUnavailable('Site does not match configured binding')
        return {'verified':True,'site_id':value.get('id')}

    def list_root(self):
        # Only the configured root is browsable; arbitrary item IDs/nextLinks are not accepted.
        root=self._get('drives/'+quote(self.drive_id,safe='')+'/items/'+quote(self.root_id,safe='')+'?$select=id,webUrl,folder,parentReference')
        web=root.get('webUrl','')
        if not web.lower().startswith(self.site_url.lower()+'/') or 'folder' not in root:raise SharePointUnavailable('Drive root is outside configured site')
        result=self._get('drives/'+quote(self.drive_id,safe='')+'/items/'+quote(self.root_id,safe='')+'/children?$top=100&$select=id,name,size,folder,file,eTag,lastModifiedDateTime')
        return {'items':[{'id':item['id'],'name':item.get('name',''),'size':item.get('size',0),'is_folder':'folder' in item,'e_tag':item.get('eTag'),'modified_at':item.get('lastModifiedDateTime')} for item in result.get('value',[])], 'has_more':bool(result.get('@odata.nextLink'))}
