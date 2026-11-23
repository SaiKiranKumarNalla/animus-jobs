import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from jobagent import ai, db, governance, opportunities, verifier

class PolicyTests(unittest.TestCase):
    def probe(self, response):
        client = httpx.Client(transport=httpx.MockTransport(lambda request: response(request)), follow_redirects=True)
        with patch.object(verifier.httpx, 'Client', return_value=client):
            return verifier.verify_job({'url':'https://example.org/jobs/123'})

    def test_blocked_is_unknown(self):
        r=self.probe(lambda q:httpx.Response(403,request=q))
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['valid'])

    def test_late_closure_is_detected(self):
        r=self.probe(lambda q:httpx.Response(200,text='<html>'+('x'*10000)+' This position has been filled </html>',request=q))
        self.assertEqual(r['status'],'broken')

    def test_hidden_template_not_closed(self):
        r=self.probe(lambda q:httpx.Response(200,text='<script>this position has been filled</script><main>'+('Open vacancy details '*30)+'</main>',request=q))
        self.assertTrue(r['valid'])

    def test_generic_redirect_not_live(self):
        r=self.probe(lambda q:httpx.Response(302,headers={'location':'https://example.org/'} ,request=q) if q.url.path != '/' else httpx.Response(200,text='careers '*100,request=q))
        self.assertEqual(r['status'],'unverified')

    def test_gemini_cannot_search(self):
        self.assertNotIn('gemini',opportunities.WEB_AGENTS)
        with self.assertRaises(RuntimeError):ai.ask_gemini_web('find jobs')
        with self.assertRaises(RuntimeError):opportunities.web_ask('find jobs','gemini')

    def test_vacancy_portals_and_real_ats_links(self):
        self.assertTrue(verifier.is_generic_job_url('https://example.org/fr/careers')[0])
        self.assertTrue(verifier.is_generic_job_url('https://www.linkedin.com/jobs/medical-imaging-jobs')[0])
        self.assertFalse(verifier.is_generic_job_url('https://www.linkedin.com/jobs/view/4332569853/')[0])
        self.assertFalse(verifier.is_generic_job_url('https://example.org/careers?gh_jid=123')[0])

    def test_content_bound_gate_and_protected_cleanup(self):
        with tempfile.TemporaryDirectory() as td, patch.object(db,'DB_PATH',Path(td)/'test.db'):
            db.init()
            job={'id':'g:1','source':'radar','title':'Scientist','company':'Company','location':'France','url':'https://example.org/jobs/1','description':'test','extra':{'found_by':'gemini+web','approved_by':'codex'}}
            self.assertFalse(db.upsert_job(job))
            key=governance.digest(job)
            self.assertEqual(db.one('SELECT count(*) n FROM jobs')['n'],0)
            db.execute("UPDATE job_proposals SET status='approved',reviewer='gemini' WHERE digest=?",(key,))
            self.assertFalse(db.upsert_job(job))
            db.execute("UPDATE job_proposals SET status='approved',reviewer='codex' WHERE digest=?",(key,))
            self.assertTrue(db.upsert_job(job))
            changed={**job,'id':'g:2','url':'https://example.org/jobs/2'}
            self.assertFalse(db.upsert_job(changed))
            db.execute("UPDATE jobs SET status='applying' WHERE id='g:1'")
            jobs=db.rows('SELECT * FROM jobs')
            with patch.object(verifier,'verify_job',return_value={'valid':False,'status':'broken','http_status':404,'reason':'HTTP 404'}):
                self.assertEqual(verifier.verify_jobs_batch(jobs,prune=True)['pruned'],0)
            db.execute("UPDATE jobs SET status='new' WHERE id='g:1'")
            with patch.object(verifier,'verify_job',return_value={'valid':False,'status':'unverified','http_status':403,'reason':'blocked'}):
                self.assertEqual(verifier.verify_jobs_batch(db.rows('SELECT * FROM jobs'),prune=True)['pruned'],0)
            with patch.object(verifier,'verify_job',return_value={'valid':False,'status':'broken','http_status':404,'reason':'HTTP 404'}):
                self.assertEqual(verifier.verify_jobs_batch(db.rows('SELECT * FROM jobs'),prune=True)['pruned'],1)
            self.assertEqual(db.one("SELECT status FROM jobs WHERE id='g:1'")['status'],'archived')

    def test_reviewed_import_threshold_resume_and_distinct_locations(self):
        import hashlib
        from datetime import datetime, timezone
        from jobagent.reviewed_import import import_file
        with tempfile.TemporaryDirectory() as td, patch.object(db,'DB_PATH',Path(td)/'test.db'):
            db.init()
            db.execute("INSERT INTO resumes(text,is_master) VALUES ('resume',1)")
            job={'id':'a:1','source':'apify_codex','title':'Scientist','company':'Company',
                 'location':'Paris','url':'https://example.org/jobs/123','description':'description',
                 'posted_at':datetime.now(timezone.utc).isoformat(),
                 'extra':{'fit_review':{'reviewer':'codex','score':50,'reason':'reason',
                                      'source_evidence':'source explicitly lists recruitment'}}}
            payload={'resume_sha256':hashlib.sha256(b'resume').hexdigest(),'jobs':[job]}
            path=Path(td)/'review.json'
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):import_file(path)
            job['extra']['fit_review']['score']=70
            path.write_text(json.dumps(payload))
            self.assertTrue(import_file(path)[0]['inserted'])
            job.update(id='a:2',location='Lyon',url='https://example.org/jobs/456')
            path.write_text(json.dumps(payload))
            self.assertTrue(import_file(path)[0]['inserted'])
            self.assertEqual(db.deduplicate_jobs()['deleted_duplicates'],0)
            payload['resume_sha256']='stale'
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):import_file(path)

if __name__=='__main__':unittest.main()
