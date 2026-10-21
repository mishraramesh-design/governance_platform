"""Default-deny API boundary, including legacy routers and object downloads.

Authentication happens before any legacy handler. Resource IDs are resolved to
their project/owner here so a missing check in a handler cannot expose an object.
Existing handler-specific acting-role and segregation checks still apply.
"""
from fastapi import Depends, HTTPException, Request
import auth
from database import db

PUBLIC = {'/api/', '/api/auth/status', '/api/auth/demo-login', '/api/health'}
OBJECTS = {
    'findings': ('findings', 'project_id'), 'reports': ('reports', 'project_id'),
    'artifacts': ('artifacts', 'project_id'), 'adjudications': ('adjudications', 'project_id'),
}
ROLE_CHECKED_WRITES = ('/api/events/simulate', '/api/edge-clients/submit', '/api/edge-clients/simulate')


async def protect_api(request: Request, credentials=Depends(auth.bearer_scheme)):
    path = request.url.path.rstrip('/') or '/'
    if request.url.path in PUBLIC or path in PUBLIC or (path == '/api/auth/users' and auth.demo_enabled()):
        return
    user = await auth.get_current_user(credentials)
    request.state.user = user
    project_ids = []
    for value in (request.path_params.get('project_id'), request.query_params.get('project_id')):
        if value:
            project_ids.append(value)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        content_type = request.headers.get('content-type', '')
        if content_type.startswith('application/json'):
            try:
                body = await request.json()
            except ValueError:
                body = {}
            if isinstance(body, dict) and body.get('project_id'):
                project_ids.append(str(body['project_id']))
        elif content_type.startswith(('multipart/form-data', 'application/x-www-form-urlencoded')):
            form = await request.form()
            if form.get('project_id'):
                project_ids.append(str(form['project_id']))
    parts = path.split('/')
    if len(parts) >= 4 and parts[2] in OBJECTS and parts[3] not in ('generate',):
        collection, field = OBJECTS[parts[2]]
        item = await db[collection].find_one({'id': parts[3]}, {'_id': 0, field: 1})
        if not item:
            # Older immutable repository snapshots remain addressable by ID.
            archived = await db.repo_audit_history.find_one(
                {'collection': collection, 'record_id': parts[3]}, {'_id': 0, 'project_id': 1})
            item = archived
        if not item:
            raise HTTPException(404, 'Record not found.')
        project_ids.append(item[field])
    if path.startswith('/api/projects/'):
        project_ids.append(parts[3])
    if path.startswith('/api/edge-clients/bundles/'):
        item = await db.edge_bundles.find_one({'id': parts[4]}, {'project_id': 1})
        if not item:
            raise HTTPException(404, 'Bundle not found.')
        project_ids.append(item['project_id'])
    if path.startswith('/api/studio/runs/'):
        item = await db.studio_runs.find_one({'id': parts[4], 'created_by_user_id': user['id']}, {'id': 1})
        if not item:
            raise HTTPException(404, 'Studio run not found.')
    for project_id in set(project_ids):
        await auth.require_project_access(user, project_id)
    if path.startswith(('/api/ledger', '/api/admin/')):
        await auth.require_platform_admin(user)
    elif path in ('/api/harness/config', '/api/harness/llm-calls'):
        if project_ids:
            if request.method != 'GET':
                for project_id in set(project_ids):
                    roles = await auth.roles_for(user['id'], project_id)
                    if not set(roles) & auth.GOVERNANCE_ROLES:
                        raise HTTPException(403, 'Project governance role required.')
        else:
            await auth.require_platform_admin(user)
    elif path.startswith('/api/mlops/'):
        await auth.require_platform_admin(user)
    elif path in ('/api/dashboard', '/api/edge-clients/contributions', '/api/edge-clients/bundles') and not project_ids:
        await auth.require_platform_admin(user)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        governed = path.startswith(('/api/studio/', '/api/testing-workspace/', '/api/admin/', '/api/ledger'))
        role_checked = (path in ROLE_CHECKED_WRITES or path.endswith(('/triage', '/decide')))
        if not governed and not role_checked:
            await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
            if project_ids:
                for project_id in set(project_ids):
                    if not set(await auth.roles_for(user['id'], project_id)) & auth.GOVERNANCE_ROLES:
                        raise HTTPException(403, 'Project governance role required for this change.')
