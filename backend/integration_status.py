"""Public-to-tenant status without secrets or private SharePoint addresses."""
import app as core
from file_api import enabled
from email_alerts import smtp_configured

@core.app.get('/ops/integrations')
def integrations(user:core.Auth):
    return {'sharepoint':{'status':'runtime_authorization_pending','configured':False,'binary_transfer_enabled':False,'note':'A ChatGPT connection does not authorize the private application. Runtime Microsoft identity, scoped library binding and file controls are required.'},'notifications':{'external_delivery_enabled':bool(smtp_configured()),'worker_required':True},'storage':{'binary_http_enabled':enabled()}}
