"""Explicit role scopes for private operational features."""
CAPABILITIES = {
    'admin': {'plan.read','plan.write','documents.read','documents.write','documents.review','tasks.read','tasks.write','users.manage','audit.read'},
    'editor': {'plan.read','plan.write','documents.read','documents.write','tasks.read','tasks.write'},
    'reviewer': {'plan.read','documents.read','documents.review','tasks.read','tasks.write'},
    'planner': {'plan.read','plan.write','tasks.read','tasks.write'},
    'viewer': {'plan.read','documents.read','tasks.read'},
}

def capabilities(role):
    return sorted(CAPABILITIES.get(role, set()))


def planner_path_allowed(path):
    return path in {'/me','/auth/logout','/auth/logout-all','/auth/mfa/setup','/auth/mfa/confirm','/ops/bootstrap','/ops/dashboard','/ops/integrations','/ops/branding','/ops/branding/logo'} or path.startswith(('/ops/services','/ops/assignments','/ops/tasks'))
