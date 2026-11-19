import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from workout_coach.lib.weekly_prescription import PublishError, publish_week, render_week, validate_week
from workout_coach.lib.adherence import load_plans, plan_windows

class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch('shared.person_paths.WORKOUT_TRACKER_ROOT', Path(self.tmp.name)); p.start(); self.addCleanup(p.stop)
        self.doc = {'week_start':'2026-11-23','week_end':'2026-11-29','as_of':'2026-11-19', 'sessions':[{'id':'a','date':'2026-11-23','type':'Upper','duration_min':60,'goal':'Press practice','exercises':[{'name':'Flat Barbell Bench Press','sets':[{'reps':'8-10','load_kg':40},{'reps':8,'load_kg':40}]}]}]}
        self.tracker = {'weekly_plan':dict(week_start='2026-11-23',week_end='2026-11-29',as_of='2026-11-19',session_count=1,session_target_min=60)}

    def test_amendment_uses_authoritative_sessions_and_is_retry_safe(self):
        second = copy.deepcopy(self.doc['sessions'][0])
        second.update(id='b', date='2026-11-27')
        self.doc['sessions'].append(second)
        snapshot = self.tracker['weekly_plan']
        snapshot.update(session_count=2, observed_revision=0)
        original = publish_week('Person', self.doc, self.tracker)
        snapshot.update(as_of='2026-11-25', observed_revision=1)
        self.tracker['existing_week'] = {'revision': 1, 'prescription': {'sessions': []}}
        replacement = copy.deepcopy(second)
        replacement['exercises'][0]['sets'][1]['load_kg'] = 42
        amendment = {'replacements': [replacement]}

        revised = publish_week('Person', amendment, self.tracker, amend=True)
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(publish_week('Person', amendment, self.tracker, amend=True), revised)
        record = json.loads(Path(revised['prescription_path']).read_text())
        self.assertEqual(record['prescription']['sessions'], [self.doc['sessions'][0], replacement])
        self.assertTrue(Path(original['prescription_path']).is_file())

        replacement['exercises'][0]['sets'][1]['load_kg'] = 44
        with self.assertRaises(PublishError) as failure:
            publish_week('Person', amendment, self.tracker, amend=True)
        self.assertEqual(failure.exception.kind, 'stale_snapshot')
        folder = Path(revised['prescription_path']).parent
        self.assertEqual(len(list(folder.glob('*.json'))), 2)

        snapshot['observed_revision'] = 2
        self.tracker['existing_week']['revision'] = 2
        historical = {**self.doc['sessions'][0], 'goal': 'Changed past session'}
        with self.assertRaises(PublishError) as failure:
            publish_week('Person', {'replacements': [historical]}, self.tracker, amend=True)
        self.assertEqual(failure.exception.kind, 'history_conflict')

    def test_guarded_draft_rejects_stale_snapshot_and_allows_intentional_reversion(self):
        snapshot = self.tracker['weekly_plan']
        snapshot['observed_revision'] = 0
        original = publish_week('Person', self.doc, self.tracker)
        self.assertEqual(publish_week('Person', self.doc, self.tracker), original)
        changed = copy.deepcopy(self.doc)
        changed['sessions'][0]['goal'] = 'Changed before lifting'
        with self.assertRaises(PublishError) as failure:
            publish_week('Person', changed, self.tracker)
        self.assertEqual(failure.exception.kind, 'stale_snapshot')

        snapshot['observed_revision'] = 1
        self.assertEqual(publish_week('Person', changed, self.tracker)['revision'], 2)
        snapshot['observed_revision'] = 2
        self.assertEqual(publish_week('Person', self.doc, self.tracker)['revision'], 3)

    def test_validation_points_to_the_failed_set(self):
        self.doc['sessions'][0]['exercises'][0]['sets'][1]['load_kg'] = -1
        with self.assertRaises(PublishError) as failure:
            publish_week('Person', self.doc, self.tracker)
        self.assertEqual(failure.exception.kind, 'validation')
        self.assertEqual(failure.exception.issues, ['sessions[0].exercises[0].sets[1]: invalid set dose'])

    def test_replay_future_and_projection(self):
        result = publish_week('Person',self.doc,self.tracker)
        self.assertEqual(result,publish_week('Person',self.doc,self.tracker))
        self.assertEqual(load_plans('Person',date(2026,11,22)),[])
        plans = load_plans('Person',date(2026,11,24))
        self.assertEqual(plans[0]['workouts'][0]['session_id'],'a')
        self.assertEqual(plans[0]['workouts'][0]['slots'][0]['prescribed_sets'],2)
        self.assertEqual(plan_windows(plans,date(2026,11,30))[0][1:],(date(2026,11,23),date(2026,11,30)))
        self.assertNotIn('Press practice',Path(result['workout_md_path']).read_text())
        Path(result['workout_md_path']).write_text('partial')
        publish_week('Person',self.doc,self.tracker)
        self.assertEqual(Path(result['workout_md_path']).read_text(),render_week(self.doc))
    def test_past_session_immutable(self):
        publish_week('Person',self.doc,self.tracker)
        revised = copy.deepcopy(self.doc); revised['as_of']='2026-11-25'; revised['sessions'][0]['goal']='Changed'
        self.tracker['weekly_plan']['as_of']='2026-11-25'
        with self.assertRaisesRegex(ValueError,'past dated'): publish_week('Person',revised,self.tracker)
    def test_restrictions_and_branches_block(self):
        self.tracker['exercise_fit']={'excluded':['Flat Barbell Bench Press']}
        self.doc['sessions'][0]['exercises'][0]['cue']='If tired, skip it'
        errors,_ = validate_week(self.doc,self.tracker)
        self.assertTrue(any('excluded' in e for e in errors)); self.assertTrue(any('cue' in e for e in errors))
        with self.assertRaises(ValueError): publish_week('Person',self.doc,self.tracker)

    def test_scoped_restriction_and_unknown_date(self):
        self.tracker['exercise_fit'] = {'default_gym':'A', 'restrictions':[{'exercise':'Flat Barbell Bench Press','location':'A','start_date':'2026-11-23'}]}
        errors, warnings = validate_week(self.doc,self.tracker)
        self.assertTrue(any('excluded' in x for x in errors))
        self.doc['sessions'][0]['gym'] = 'B'
        errors, warnings = validate_week(self.doc,self.tracker)
        self.assertFalse(errors)
        self.doc['sessions'][0]['gym'] = 'A'
        self.doc['sessions'][0]['date'] = None
        errors, warnings = validate_week(self.doc,self.tracker)
        self.assertTrue(any('eligibility' in x for x in errors))

    def test_unknown_variant_blocks_only_when_the_other_scopes_can_match(self):
        self.tracker["exercise_fit"] = {
            "default_gym": "A",
            "restrictions": [{"exercise": "Flat Barbell Bench Press", "location": "A",
                              "variant": "Wide grip", "end_date": "2026-11-24"}],
        }
        session = self.doc["sessions"][0]
        errors, _ = validate_week(self.doc, self.tracker)
        self.assertTrue(any("eligibility" in error for error in errors))

        session["gym"] = "B"
        self.assertFalse(validate_week(self.doc, self.tracker)[0])
        session["gym"] = "A"
        session["date"] = "2026-11-25"
        self.assertFalse(validate_week(self.doc, self.tracker)[0])

        session["date"] = "2026-11-23"
        session["exercises"][0]["variant"] = "Neutral grip"
        self.assertFalse(validate_week(self.doc, self.tracker)[0])
        self.assertIn("Neutral grip", render_week(self.doc))

    def test_reject_qa_branch_patterns_and_unknown_fields(self):
        for cue in ('Walk when unusually sore.', 'Switch to walking when feeling exhausted.', 'Take an easier session on a bad day.'):
            doc = copy.deepcopy(self.doc)
            doc['sessions'][0]['exercises'][0]['cue'] = cue
            self.assertTrue(validate_week(doc, self.tracker)[0], cue)
        doc = copy.deepcopy(self.doc); doc['sessions'][0]['fallback'] = 'walk'
        self.assertTrue(validate_week(doc, self.tracker)[0])

    def test_finite_working_and_plain_text(self):
        for mutate in ('nan', 'warmup', 'cardio', 'carriage'):
            doc = copy.deepcopy(self.doc)
            ex = doc['sessions'][0]['exercises'][0]
            if mutate == 'nan': ex['sets'][0]['load_kg'] = float('nan')
            if mutate == 'warmup':
                for item in ex['sets']: item['warmup'] = True
            if mutate == 'cardio': ex['name'] = 'Running'
            if mutate == 'carriage': doc['sessions'][0]['type'] = 'Upper\r# Walk'
            self.assertTrue(validate_week(doc, self.tracker)[0], mutate)

    def test_past_first_session_rejected(self):
        self.doc['as_of'] = self.tracker['weekly_plan']['as_of'] = '2026-11-24'
        with self.assertRaisesRegex(ValueError, 'before as_of'):
            publish_week('Person', self.doc, self.tracker)

    def test_revision_does_not_duplicate_future_slots(self):
        first = copy.deepcopy(self.doc)
        first['sessions'].append(copy.deepcopy(first['sessions'][0]))
        first['sessions'][1].update(id='b', date='2026-11-27')
        self.tracker['weekly_plan']['session_count'] = 2
        publish_week('Person', first, self.tracker)
        second = copy.deepcopy(first); second['as_of'] = '2026-11-25'
        second['sessions'][1]['exercises'][0]['sets'][0]['load_kg'] = 42
        self.tracker['weekly_plan']['as_of'] = second['as_of']
        publish_week('Person', second, self.tracker)
        plans = load_plans('Person', date(2026,11,29))
        ids = [[w['session_id'] for w in p['workouts']] for p in plans]
        self.assertEqual(ids, [['a'], ['b']])
        self.assertEqual([w['plan_date'] for w in plans], ['2026-11-23', '2026-11-25'])

    def test_flexible_slot_carried_through_three_revisions_counts_once(self):
        self.doc["sessions"][0]["date"] = None
        for revision, as_of in enumerate(("2026-11-19", "2026-11-24", "2026-11-25"), 1):
            self.doc["as_of"] = self.tracker["weekly_plan"]["as_of"] = as_of
            self.doc["sessions"][0]["reason"] = f"Revision {revision}"
            publish_week("Person", self.doc, self.tracker)

        plans = load_plans("Person", date(2026, 11, 29))
        self.assertEqual([len(plan["workouts"]) for plan in plans], [0, 0, 1])
        self.assertTrue(all(plan["parse_notes"] for plan in plans[:2]))
        self.assertEqual(plans[-1]["workouts"][0]["session_id"], "a")

    def test_training_days_and_owner(self):
        self.tracker['weekly_plan']['training_days'] = ['2026-11-24']
        self.assertTrue(validate_week(self.doc,self.tracker)[0])
        self.tracker['weekly_plan']['training_days'] = ['2026-11-23']
        self.tracker['weekly_plan']['person'] = 'Other'
        with self.assertRaisesRegex(ValueError, 'person differs'):
            publish_week('Person',self.doc,self.tracker)

    def test_upcoming_and_corrupt_optional_history(self):
        from workout_coach.lib.weekly_prescription import latest_published_weeks
        publish_week('Person', self.doc, self.tracker)
        folder = Path(self.tmp.name) / 'plans' / 'Person' / 'weekly'
        (folder / 'bad.json').write_text('{')
        weeks = latest_published_weeks('Person', date(2026,11,19))
        self.assertEqual(len(weeks), 1)
        self.assertEqual(load_plans('Person', date(2026,11,23))[0]['parse_errors'], [])

    def test_revision_keeps_historical_slots_under_new_constraints(self):
        original = copy.deepcopy(self.doc)
        original['sessions'].append(copy.deepcopy(original['sessions'][0]))
        original['sessions'][1].update(id='b', date='2026-11-27')
        self.tracker['weekly_plan']['session_count'] = 2
        publish_week('Person', original, self.tracker)
        revised = copy.deepcopy(original); revised['as_of'] = '2026-11-25'
        revised['sessions'][1]['exercises'][0]['name'] = 'Incline Barbell Bench Press'
        revised['sessions'][1]['duration_min'] = 45
        revised['sessions'][1]['reason'] = 'Continue because the earlier session was harder.'
        self.tracker['weekly_plan'].update(as_of='2026-11-25', session_target_min=45, training_days=['2026-11-27'])
        self.tracker['exercise_fit'] = {'restrictions':[{'exercise':'Flat Barbell Bench Press'}]}
        result = publish_week('Person', revised, self.tracker)
        self.assertEqual(result['revision'], 2)
        from workout_coach.lib.adherence import weekly_plan_for_history
        record = json.loads(Path(result['prescription_path']).read_text())
        self.assertEqual(len(weekly_plan_for_history(record)['workouts']), 1)
        self.assertEqual(len(weekly_plan_for_history(record, include_prior_slots=True)['workouts']), 2)
