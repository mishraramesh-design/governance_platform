import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class BrandingTests(unittest.TestCase):
 def test_product_shell(self):
  html=(ROOT/'frontend/public/index.html').read_text()
  self.assertIn('<title>Governance AI Studio</title>',html)
  self.assertNotIn('posthog',html.lower())
  self.assertNotIn('emergent',html.lower())
  self.assertIn('favicon.svg',html)
  manifest=json.loads((ROOT/'frontend/public/manifest.json').read_text())
  self.assertEqual(manifest['name'],'Governance AI Studio')
  self.assertTrue((ROOT/'frontend/public/favicon.svg').exists())
 def test_no_vendor_integrations(self):
  for name in ['frontend/package.json','frontend/craco.config.js']:
   self.assertNotIn('emergent',(ROOT/name).read_text().lower())
if __name__=='__main__': unittest.main()
