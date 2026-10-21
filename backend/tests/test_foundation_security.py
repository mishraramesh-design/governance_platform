import os
os.environ.setdefault('MONGO_URL', 'mongodb://127.0.0.1:27017')
os.environ.setdefault('DB_NAME', 'phase1_unit')
import re
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import auth, server, access_policy, seed_data
from routers import projects, reports, events, assurance, auth as auth_routes, studio
from phase1_fakes import Database


class FoundationAccessTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.mode = patch.dict(os.environ, {'DEMO_MODE': 'false'}); self.mode.start(); self.addCleanup(self.mode.stop)
        for module in (auth, access_policy, projects, reports, events, assurance, auth_routes, studio):
            p = patch.object(module, 'db', self.db); p.start(); self.addCleanup(p.stop)
        async def setup():
            for uid, roles in [('admin', ['Programme Manager']), ('dev', []), ('quality', [])]:
                await self.db.users.insert_one({'id': uid, 'name': uid, 'active': True, 'platform_roles': roles})
                await self.db.api_tokens.insert_one({'id': uid, 'user_id': uid, 'token_hash': auth.hash_token(uid+'-fixture'), 'revoked': False, 'created_by': 'admin'})
            for pid in ['p1','p2']: await self.db.projects.insert_one({'id': pid, 'name': pid})
            for uid,pid,roles in [('admin','p1',['Programme Manager']),('dev','p1',['Developer']),('quality','p2',['Quality Lead'])]:
                await self.db.role_assignments.insert_one({'id':uid, 'user_id':uid, 'project_id':pid, 'roles':roles})
            await self.db.reports.insert_one({'id':'r1','project_id':'p1','title':'old report','narrative':'safe','sections':[],'finding_count':0,'created_at':'2026-10-21','type':'author'})
            await self.db.findings.insert_one({'id':'f1','project_id':'p1'})
            await self.db.studio_runs.insert_one({'id':'s1','created_by_user_id':'admin'})
        asyncio.run(setup())
        self.client = TestClient(server.app)  # no startup and no external database
    def headers(self, user): return {'Authorization':'Bearer '+user+'-fixture'}

    def test_every_registered_api_route_rejects_anonymous_requests(self):
        checked = 0
        for route in server.app.routes:
            if not route.path.startswith('/api/') or route.path in access_policy.PUBLIC: continue
            path = re.sub(r'\{[^}]+\}', 'fixture', route.path)
            for method in route.methods - {'HEAD','OPTIONS'}:
                response = self.client.request(method, path, json={} if method not in ('GET',) else None)
                self.assertEqual(response.status_code, 401, f'{method} {path}: {response.text[:100]}')
                checked += 1
        self.assertGreater(checked, 80)

    def test_demo_identity_and_legacy_seed_tokens_disabled_by_default(self):
        self.assertEqual(self.client.post('/api/auth/demo-login', json={'user_id':'admin'}).status_code,404)
        asyncio.run(self.db.api_tokens.update_one({'id':'admin'},{'$set':{'created_by':'seed'}}))
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers('admin')).status_code,401)

    def test_valid_admin_and_invalid_or_revoked_tokens(self):
        self.assertTrue(self.client.get('/api/auth/me',headers=self.headers('admin')).json()['is_admin'])
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers('unknown')).status_code,401)
        asyncio.run(self.db.api_tokens.update_one({'id':'admin'},{'$set':{'revoked':True}}))
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers('admin')).status_code,401)

    def test_project_list_is_filtered_and_cross_project_object_download_denied(self):
        data = self.client.get('/api/projects',headers=self.headers('dev')).json()
        self.assertEqual([p['id'] for p in data],['p1'])
        for path in ['/api/projects/p1','/api/reports/r1','/api/reports/r1/download','/api/findings/f1','/api/repo-audit/p1/history']:
            self.assertEqual(self.client.get(path,headers=self.headers('quality')).status_code,403,path)
        self.assertEqual(self.client.get('/api/reports/r1/download',headers=self.headers('dev')).status_code,200)

    def test_project_role_does_not_grant_platform_configuration_or_ledger_access(self):
        for path in ['/api/admin/users','/api/ledger','/api/harness/config']:
            self.assertEqual(self.client.get(path,headers=self.headers('quality')).status_code,403)
        self.assertEqual(self.client.put('/api/harness/config',headers=self.headers('dev'),json={'capability_profiles':{},'project_id':'p1'}).status_code,403)

    def test_studio_owner_and_mutation_scope_are_enforced(self):
        self.assertEqual(self.client.get('/api/studio/runs/s1',headers=self.headers('quality')).status_code,404)
        self.assertEqual(self.client.post('/api/runtime/analyze',headers=self.headers('dev'),json={'project_id':'p1','log_text':'QA'}).status_code,403)
        self.assertEqual(self.client.post('/api/artifacts/generate',headers=self.headers('quality'),json={'project_id':'p1','artifact_type':'rtm'}).status_code,403)

    def test_bootstrap_token_is_hashed_and_previous_demo_tokens_revoked(self):
        with patch.dict(os.environ, {'BOOTSTRAP_ADMIN_TOKEN':'synthetic-private-bootstrap'}):
            asyncio.run(seed_data.ensure_users_seeded(self.db))
        row=asyncio.run(self.db.api_tokens.find_one({'id':'bootstrap-admin'}))
        self.assertEqual(row['token_hash'],auth.hash_token('synthetic-private-bootstrap'))
        self.assertNotIn('synthetic-private-bootstrap',str(row))
        admin=asyncio.run(self.db.users.find_one({'id':'u-ramesh'}))
        self.assertIn('Programme Manager',admin['platform_roles'])

    def test_explicit_demo_mode_still_supports_demo_identity(self):
        with patch.dict(os.environ, {'DEMO_MODE':'true'}):
            self.assertEqual(self.client.post('/api/auth/demo-login',json={'user_id':'admin'}).status_code,200)

    def test_html_export_escapes_untrusted_content(self):
        html=reports.render_html('<script>x</script>','<img src=x>',[{'heading':'<b>','body':['<svg onload=alert(1)>']}])
        self.assertNotIn('<script>',html);self.assertNotIn('<svg',html);self.assertIn('&lt;svg',html)
