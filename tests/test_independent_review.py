import json
from pathlib import Path
import pytest
from evaluation.independent_review import agreement, next_item, record, status


@pytest.fixture
def frozen(tmp_path):
    d=tmp_path/'evaluation/real';d.mkdir(parents=True)
    files={'manifest.json':{'snapshot_sha256':'fixture'},'candidate-items.json':{
        'entities':[{'item_id':'e1','document_id':'d','start':0,'end':4,'entity_text':'Acme','label':'Startup','notes':'Prepared answer must be hidden'},
                    {'item_id':'e2','document_id':'d','start':5,'end':8,'entity_text':'API'}],
        'relations':[{'item_id':'r1','document_id':'d','subject':'Acme','object':'API','span_text':'Acme API'},
                     {'item_id':'r2','document_id':'d','subject':'Acme','object':'Other','span_text':'Acme Other'}]},
        'guidelines.json':{'entity_types':['Startup','Technology'],'relation_types':['MENTIONS']}}
    for name,x in files.items():(d/name).write_text(json.dumps(x))
    (d/'records.jsonl').write_text(json.dumps({'record_id':'d','title':'Test-only source','source_url':'https://example.test','text':'Acme API Other'})+'\n')
    return tmp_path


def submit(root,reviewer,kind,item,label,confirmed=True):
    return record({'round':'real','reviewer':reviewer,'kind':kind,'item_id':item,'label':label,
                   'personal_independence_confirmation':confirmed},root)


def test_blind_items_do_not_reveal_prepared_labels_or_notes(frozen):
    x=next_item('real','mehmet','entities',frozen)
    assert x['completed']==0 and x['total']==2
    assert status('real',frozen)['status']=='requires_personal_decisions'
    assert 'label' not in x['candidate'] and 'notes' not in x['candidate']
    assert x['source']['text']=='Acme API Other'
    assert not (frozen/'evaluation/independent-review').exists()


def test_confirmation_and_valid_label_required_without_prefilling(frozen):
    with pytest.raises(ValueError,match='personal review'):
        submit(frozen,'mehmet','entities','e1','Startup',False)
    with pytest.raises(ValueError,match='invalid/missing label'):
        submit(frozen,'mehmet','entities','e1','')
    assert submit(frozen,'mehmet','entities','e1','Startup')['saved']
    assert next_item('real','mehmet','entities',frozen)['candidate']['item_id']=='e2'
    with pytest.raises(ValueError,match='already recorded'):
        submit(frozen,'mehmet','entities','e1','NONE')
    assert next_item('real','sueda','entities',frozen)['completed']==0


def test_agreement_waits_for_actual_complete_individual_decisions(frozen):
    with pytest.raises(ValueError,match='actual decisions'):
        agreement('real',frozen)
    for who in ['sueda','mehmet']:
        for kind,items in [('entities',[('e1','Startup'),('e2','NONE')]),('relations',[('r1','MENTIONS'),('r2','NONE')])]:
            for item,label in items:submit(frozen,who,kind,item,label)
    r=agreement('real',frozen)
    assert r['results']['entities']['cohen_kappa']==1
    assert r['results']['relations']['raw_agreement']==1
    assert len(r['review_file_sha256'])==2
    assert status('real',frozen)['status']=='complete_for_pairwise_agreement'
    assert not (frozen/'evaluation/real/workbooks').exists()


def test_source_changes_require_reconciliation(frozen):
    submit(frozen,'mehmet','entities','e1','Startup')
    p=frozen/'evaluation/real/records.jsonl';p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='Frozen source changed'):
        next_item('real','mehmet','entities',frozen)


def test_source_assisted_mixed_files_are_not_independent_kappa():
    root = Path(__file__).resolve().parents[1]
    for reviewer in ('sueda', 'mehmet'):
        path = root/'evaluation/independent-review/mixed'/f'{reviewer}.json'
        data=json.loads(path.read_text())
        assert data['independent_human_attestation'] is False
        assert data['kappa_eligible'] is False
        assert len(data['decisions']['entities'])==276
        assert len(data['decisions']['relations'])==108


def test_assisted_records_do_not_prefill_personal_reviews(frozen):
    d=frozen/'evaluation/independent-review/real';d.mkdir(parents=True)
    p=d/'mehmet.json';p.write_text(json.dumps({'method':'team_authorized_source_assisted_review','complete':True,'decisions':{'entities':{'e1':{'label':'Startup'}},'relations':{}}}))
    assert next_item('real','mehmet','entities',frozen)['completed']==0
    assert status('real',frozen)['assisted_records_preserved_outside_direct_store']
    assert json.loads(p.read_text())['complete'] is True


def test_current_real_review_uses_frozen_expanded_pool():
    from evaluation.independent_review import ROOT
    assert next_item('real','sueda','entities',ROOT)['total']==776
    assert next_item('real','sueda','relations',ROOT)['total']==100


def test_direct_store_rejects_assisted_method_even_with_confirmation_flags(frozen):
    submit(frozen,'mehmet','entities','e1','Startup')
    p=frozen/'evaluation/independent-review/real/direct/mehmet.json'
    x=json.loads(p.read_text());x['method']='team_authorized_source_assisted_review';p.write_text(json.dumps(x))
    with pytest.raises(ValueError,match='non-independent assisted'):
        next_item('real','mehmet','entities',frozen)
