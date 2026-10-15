"""Private, tenant-scoped services, staffing, reviews and task workflows.

No binary upload, external message, or destructive retention is enabled here.
Approval of metadata alone never accredits a worker: evidence must include a
registered binary version and the required review must match current metadata.
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, mapped_column

import app as core
from access_policy import capabilities
from document_history import _document_for_tenant
from file_records import DocumentFileVersion
from requirements_api import DocumentPolicy, Requirement


def now():
    return datetime.now(timezone.utc)


class Service(core.Base):
    __tablename__ = 'services'
    __table_args__ = (UniqueConstraint('tenant_id','code',name='uq_service_tenant_code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(160))
    client: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(200))
    supervisor: Mapped[str] = mapped_column(String(150))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20),default='scheduled')
    version: Mapped[int] = mapped_column(Integer,default=1)
    closure_json: Mapped[str | None] = mapped_column(Text,nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)


class Assignment(core.Base):
    __tablename__ = 'personnel_assignments'
    __table_args__ = (UniqueConstraint('tenant_id','worker_id','work_date',name='uq_assignment_worker_day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey('workers.id'),index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey('services.id'),nullable=True)
    work_date: Mapped[date] = mapped_column(Date,index=True)
    state: Mapped[str] = mapped_column(String(20))
    actual: Mapped[str] = mapped_column(String(20),default='pending')
    version: Mapped[int] = mapped_column(Integer,default=1)


class AssignmentChange(core.Base):
    __tablename__ = 'assignment_changes'
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('personnel_assignments.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class ProjectRequirement(core.Base):
    __tablename__ = 'project_requirements'
    __table_args__ = (UniqueConstraint('tenant_id','project_id','requirement_id',name='uq_project_requirement'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    requirement_id: Mapped[int] = mapped_column(ForeignKey('requirements.id'))


class WorkerEvidence(core.Base):
    __tablename__ = 'worker_evidence'
    __table_args__ = (UniqueConstraint('document_id',name='uq_worker_evidence_document'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey('workers.id'))
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'))


class Review(core.Base):
    __tablename__ = 'document_reviews'
    __table_args__ = (UniqueConstraint('tenant_id','document_id',name='uq_document_review'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'))
    state: Mapped[str] = mapped_column(String(20),default='pending')
    version: Mapped[int] = mapped_column(Integer,default=0)
    fingerprint: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500),default='')
    updated_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class ReviewEvent(core.Base):
    __tablename__ = 'document_review_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    state: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class Task(core.Base):
    __tablename__ = 'operation_tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'),index=True)
    title: Mapped[str] = mapped_column(String(200))
    assignee_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    service_id: Mapped[int | None] = mapped_column(ForeignKey('services.id'),nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey('documents.id'),nullable=True)
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20),default='open')
    version: Mapped[int] = mapped_column(Integer,default=1)


def permit(capability):
    def dependency(user: core.Auth):
        if capability not in capabilities(user.role):
            raise HTTPException(403,'Insufficient permissions')
        return user
    return dependency


PlanRead = Annotated[core.User,Depends(permit('plan.read'))]
PlanWrite = Annotated[core.User,Depends(permit('plan.write'))]
DocRead = Annotated[core.User,Depends(permit('documents.read'))]
TaskWrite = Annotated[core.User,Depends(permit('tasks.write'))]


def owned(db,model,tenant,identity,lock=False):
    query=select(model).where(model.id==identity,model.tenant_id==tenant)
    if lock: query=query.with_for_update()
    row=db.scalar(query)
    if row is None: raise HTTPException(404,'Resource not found')
    return row


def commit(db):
    try: db.commit()
    except (IntegrityError,OperationalError):
        db.rollback()
        raise HTTPException(409,'Concurrent change or duplicate record; refresh and retry')


class OpsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')


class ServiceIn(OpsInput):
    project_id: int = Field(gt=0)
    code: str = Field(min_length=2,max_length=60)
    name: str = Field(min_length=2,max_length=160)
    client: str = Field(min_length=2,max_length=160)
    location: str = Field(min_length=2,max_length=200)
    supervisor: str = Field(min_length=2,max_length=150)
    starts_on: date
    ends_on: date
    @model_validator(mode='after')
    def dates(self):
        if self.starts_on>self.ends_on or (self.ends_on-self.starts_on).days>365:
            raise ValueError('Invalid service period; maximum 366 days')
        return self


class AssignmentIn(OpsInput):
    worker_id: int = Field(gt=0)
    service_id: int | None = Field(default=None,gt=0)
    starts_on: date
    ends_on: date
    state: str = Field(pattern='^(terrain|rest|unassigned)$')
    replace_existing: bool = False
    expected_versions: dict[str,int] = Field(default_factory=dict,max_length=366)
    reason: str = Field(min_length=5,max_length=300)
    @model_validator(mode='after')
    def dates(self):
        if self.starts_on>self.ends_on or (self.ends_on-self.starts_on).days>365:
            raise ValueError('Invalid assignment period; maximum 366 days')
        if self.state=='terrain' and self.service_id is None:
            raise ValueError('Terrain requires a service')
        if self.state!='terrain' and self.service_id is not None:
            raise ValueError('Only terrain can have a service')
        return self


def service_payload(s):
    return {k:getattr(s,k) for k in ('id','project_id','code','name','client','location','supervisor','starts_on','ends_on','status','version')}


def assignment_payload(a):
    return {k:getattr(a,k) for k in ('id','worker_id','service_id','work_date','state','actual','version')}


def fingerprint(db,doc):
    version=db.scalar(select(func.max(DocumentFileVersion.version)).where(DocumentFileVersion.tenant_id==doc.tenant_id,DocumentFileVersion.document_id==doc.id)) or 0
    policy=db.scalar(select(DocumentPolicy).where(DocumentPolicy.tenant_id==doc.tenant_id,DocumentPolicy.document_id==doc.id))
    worker=db.scalar(select(WorkerEvidence.worker_id).where(WorkerEvidence.tenant_id==doc.tenant_id,WorkerEvidence.document_id==doc.id))
    payload=[doc.project_id,doc.title,doc.subject_type,doc.subject_name,str(doc.expires_on),version,policy.requirement_id if policy else None,str(policy.issued_on) if policy else None,worker]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()


def review_state(db,doc):
    row=db.scalar(select(Review).where(Review.tenant_id==doc.tenant_id,Review.document_id==doc.id))
    if row is None:return 'pending',0,''
    state=row.state if row.fingerprint==fingerprint(db,doc) else 'pending'
    return state,row.version,row.reason if state==row.state else 'Document changed; review required'


def evidence_valid(db,doc,as_of=None):
    state,_,_=review_state(db,doc)
    binary=db.scalar(select(DocumentFileVersion.id).where(DocumentFileVersion.tenant_id==doc.tenant_id,DocumentFileVersion.document_id==doc.id).limit(1))
    return state=='approved' and binary is not None and doc.expires_on is not None and doc.expires_on>=max(date.today(),as_of or date.today())


def worker_readiness(db,tenant,worker_id,project_id,as_of=None):
    worker=owned(db,core.Worker,tenant,worker_id)
    requirements=db.scalars(select(Requirement).join(ProjectRequirement,ProjectRequirement.requirement_id==Requirement.id).where(ProjectRequirement.tenant_id==tenant,ProjectRequirement.project_id==project_id,Requirement.tenant_id==tenant,Requirement.active==1,Requirement.required==1,Requirement.subject_type=='worker')).all()
    missing=[]
    for req in requirements:
        docs=db.scalars(select(core.Document).join(DocumentPolicy,DocumentPolicy.document_id==core.Document.id).join(WorkerEvidence,WorkerEvidence.document_id==core.Document.id).where(core.Document.tenant_id==tenant,core.Document.project_id==project_id,DocumentPolicy.tenant_id==tenant,DocumentPolicy.requirement_id==req.id,WorkerEvidence.tenant_id==tenant,WorkerEvidence.worker_id==worker_id)).all()
        if not any(evidence_valid(db,d,as_of) for d in docs):missing.append(req.id)
    return {'worker_id':worker.id,'configured':bool(requirements),'ready':bool(worker.active) and bool(requirements) and not missing,'blocking_count':len(missing),'required_count':len(requirements)}


@core.app.get('/ops/bootstrap')
def bootstrap(user:core.Auth,db:core.Db):
    people=db.scalars(select(core.Worker).where(core.Worker.tenant_id==user.tenant_id,core.Worker.active==1).order_by(core.Worker.id)).all()
    projects=db.scalars(select(core.Project).where(core.Project.tenant_id==user.tenant_id,core.Project.active==1).order_by(core.Project.id)).all()
    users=db.scalars(select(core.User).where(core.User.tenant_id==user.tenant_id,core.User.active==1).order_by(core.User.id)).all()
    return {'tenant':{'id':user.tenant_id,'name':db.get(core.Tenant,user.tenant_id).name},'me':{'id':user.id,'email':user.email,'role':user.role,'mfa_enabled':bool(user.mfa_enabled),'capabilities':capabilities(user.role)},'workers':[{'id':w.id,'full_name':w.full_name,'job_title':w.job_title} for w in people],'projects':[{'id':p.id,'name':p.name} for p in projects],'users':[{'id':u.id,'label':u.email} for u in users if user.role=='admin' or u.id==user.id]}


@core.app.get('/ops/services')
def list_services(user:PlanRead,db:core.Db):
    return [service_payload(s) for s in db.scalars(select(Service).where(Service.tenant_id==user.tenant_id).order_by(Service.starts_on.desc())).all()]


@core.app.post('/ops/services',status_code=201)
def add_service(data:ServiceIn,user:PlanWrite,_:core.Csrf,db:core.Db):
    project=owned(db,core.Project,user.tenant_id,data.project_id)
    if not project.active:raise HTTPException(409,'Project is inactive')
    row=Service(tenant_id=user.tenant_id,**data.model_dump())
    db.add(row)
    try:db.flush()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Service code already exists')
    core.add_audit(db,user,'service.create','service',row.id);commit(db);return service_payload(row)


@core.app.get('/ops/assignments')
def assignments(user:PlanRead,db:core.Db,starts_on:date,ends_on:date,worker_id:int|None=None):
    if starts_on>ends_on or (ends_on-starts_on).days>365:raise HTTPException(422,'Invalid calendar range')
    query=select(Assignment).where(Assignment.tenant_id==user.tenant_id,Assignment.work_date>=starts_on,Assignment.work_date<=ends_on)
    if worker_id is not None:owned(db,core.Worker,user.tenant_id,worker_id);query=query.where(Assignment.worker_id==worker_id)
    return [assignment_payload(a) for a in db.scalars(query.order_by(Assignment.work_date,Assignment.worker_id)).all()]


def assignment_context(data,user,db,lock=False):
    worker=owned(db,core.Worker,user.tenant_id,data.worker_id,lock)
    if not worker.active:raise HTTPException(409,'Worker is inactive')
    service=None
    if data.service_id is not None:
        service=owned(db,Service,user.tenant_id,data.service_id,lock)
        if service.status in {'completed','cancelled'} or data.starts_on<service.starts_on or data.ends_on>service.ends_on:raise HTTPException(409,'Dates are outside the active service period')
    rows=db.scalars(select(Assignment).where(Assignment.tenant_id==user.tenant_id,Assignment.worker_id==worker.id,Assignment.work_date>=data.starts_on,Assignment.work_date<=data.ends_on).with_for_update()).all()
    return worker,service,{a.work_date:a for a in rows}


@core.app.post('/ops/assignments/preview')
def preview_assignment(data:AssignmentIn,user:PlanWrite,_:core.Csrf,db:core.Db):
    worker,service,existing=assignment_context(data,user,db)
    conflicts=[assignment_payload(a) for a in existing.values() if a.state!='unassigned' and (a.state!=data.state or a.service_id!=data.service_id)]
    readiness=worker_readiness(db,user.tenant_id,worker.id,service.project_id,data.ends_on) if service else None
    return {'conflicts':conflicts,'expected_versions':{d.isoformat():a.version for d,a in existing.items()},'readiness':readiness,'days':(data.ends_on-data.starts_on).days+1}


@core.app.post('/ops/assignments')
def save_assignment(data:AssignmentIn,user:PlanWrite,_:core.Csrf,db:core.Db):
    worker,service,existing=assignment_context(data,user,db,True)
    conflicts=[a for a in existing.values() if a.state!='unassigned' and (a.state!=data.state or a.service_id!=data.service_id)]
    if conflicts and not data.replace_existing:raise HTTPException(409,{'message':'Assignment overlaps terrain or rest','conflicts':jsonable_encoder([assignment_payload(a) for a in conflicts])})
    for d,a in existing.items():
        if data.expected_versions.get(d.isoformat())!=a.version:raise HTTPException(409,'Calendar changed; preview again')
        if a.actual!='pending':raise HTTPException(409,'Recorded attendance cannot be overwritten')
    changed=0
    for offset in range((data.ends_on-data.starts_on).days+1):
        day=data.starts_on+timedelta(days=offset);a=existing.get(day)
        if a and a.state==data.state and a.service_id==data.service_id:continue
        before=assignment_payload(a) if a else {}
        if a is None:
            a=Assignment(tenant_id=user.tenant_id,worker_id=worker.id,work_date=day,state=data.state,service_id=data.service_id,actual='pending',version=1);db.add(a)
            try:db.flush()
            except (IntegrityError,OperationalError):db.rollback();raise HTTPException(409,'Calendar changed; refresh and retry')
        else:a.state=data.state;a.service_id=data.service_id;a.version+=1
        db.add(AssignmentChange(tenant_id=user.tenant_id,assignment_id=a.id,user_id=user.id,before_json=json.dumps(before,default=str),after_json=json.dumps(assignment_payload(a),default=str),reason=data.reason))
        core.add_audit(db,user,'assignment.update','assignment',a.id);changed+=1
    commit(db)
    return {'updated':changed,'readiness':worker_readiness(db,user.tenant_id,worker.id,service.project_id,data.ends_on) if service else None}


class ActualIn(OpsInput):
    actual:str=Field(pattern='^(attended|absent|rest)$')
    expected_version:int=Field(ge=1)
    reason:str=Field(min_length=5,max_length=300)


@core.app.patch('/ops/assignments/{assignment_id}/actual')
def actual(assignment_id:int,data:ActualIn,user:PlanWrite,_:core.Csrf,db:core.Db):
    a=owned(db,Assignment,user.tenant_id,assignment_id,True)
    if a.version!=data.expected_version:raise HTTPException(409,'Assignment changed')
    if a.service_id is not None:
        service=owned(db,Service,user.tenant_id,a.service_id,True)
        if service.status=='completed':raise HTTPException(409,'Service is closed')
    if a.work_date>date.today():raise HTTPException(409,'Future attendance cannot be recorded')
    if (a.state=='rest' and data.actual!='rest') or (a.state=='terrain' and data.actual=='rest') or a.state=='unassigned':raise HTTPException(422,'Attendance does not match planned state')
    before=assignment_payload(a);a.actual=data.actual;a.version+=1
    db.add(AssignmentChange(tenant_id=user.tenant_id,assignment_id=a.id,user_id=user.id,before_json=json.dumps(before,default=str),after_json=json.dumps(assignment_payload(a),default=str),reason=data.reason))
    core.add_audit(db,user,'assignment.actual','assignment',a.id);commit(db);return assignment_payload(a)


@core.app.get('/ops/assignments/{assignment_id}/history')
def assignment_history(assignment_id:int,user:PlanRead,db:core.Db):
    owned(db,Assignment,user.tenant_id,assignment_id)
    return [{'user_id':r.user_id,'before':json.loads(r.before_json),'after':json.loads(r.after_json),'reason':r.reason,'at':r.at} for r in db.scalars(select(AssignmentChange).where(AssignmentChange.tenant_id==user.tenant_id,AssignmentChange.assignment_id==assignment_id).order_by(AssignmentChange.id.desc())).all()]


class ProjectRequirementIn(OpsInput):
    requirement_id:int=Field(gt=0)


@core.app.post('/ops/projects/{project_id}/requirements',status_code=201)
def set_project_requirement(project_id:int,data:ProjectRequirementIn,user:core.AdminWrite,db:core.Db):
    owned(db,core.Project,user.tenant_id,project_id,True);owned(db,Requirement,user.tenant_id,data.requirement_id)
    row=db.scalar(select(ProjectRequirement).where(ProjectRequirement.tenant_id==user.tenant_id,ProjectRequirement.project_id==project_id,ProjectRequirement.requirement_id==data.requirement_id))
    if row is None:
        row=ProjectRequirement(tenant_id=user.tenant_id,project_id=project_id,requirement_id=data.requirement_id);db.add(row);db.flush();core.add_audit(db,user,'project.requirement','project',project_id);commit(db)
    return {'project_id':project_id,'requirement_id':data.requirement_id}


class WorkerEvidenceIn(OpsInput):
    worker_id:int=Field(gt=0)


@core.app.post('/ops/documents/{document_id}/worker')
def link_worker(document_id:int,data:WorkerEvidenceIn,user:core.Editor,db:core.Db):
    doc=owned(db,core.Document,user.tenant_id,document_id,True);worker=owned(db,core.Worker,user.tenant_id,data.worker_id)
    if doc.subject_type!='worker' or doc.subject_name!=worker.full_name:raise HTTPException(422,'Document subject does not match worker')
    row=db.scalar(select(WorkerEvidence).where(WorkerEvidence.document_id==document_id,WorkerEvidence.tenant_id==user.tenant_id))
    if row and row.worker_id!=worker.id:raise HTTPException(409,'Document already linked to another worker')
    if row is None:db.add(WorkerEvidence(tenant_id=user.tenant_id,document_id=document_id,worker_id=worker.id))
    core.add_audit(db,user,'document.worker_link','document',document_id);commit(db);return {'document_id':document_id,'worker_id':worker.id}


@core.app.get('/ops/reviews')
def reviews(user:DocRead,db:core.Db):
    docs=db.scalars(select(core.Document).where(core.Document.tenant_id==user.tenant_id).order_by(core.Document.id.desc())).all()
    result=[]
    for d in docs:
        state,version,reason=review_state(db,d)
        result.append({'id':d.id,'title':d.title,'subject_name':d.subject_name,'subject_type':d.subject_type,'project_id':d.project_id,'expires_on':d.expires_on,'expiry_status':core.doc_state(d),'state':state,'version':version,'reason':reason})
    return result


class ReviewIn(OpsInput):
    state:str=Field(pattern='^(received|in_review|observed|approved|rejected)$')
    expected_version:int=Field(ge=0)
    reason:str=Field(default='',max_length=500)


@core.app.post('/ops/documents/{document_id}/review')
def review(document_id:int,data:ReviewIn,user:core.Auth,_:core.Csrf,db:core.Db):
    cap='documents.review' if data.state in {'approved','observed','rejected'} else 'documents.write'
    if cap not in capabilities(user.role) and 'documents.review' not in capabilities(user.role):raise HTTPException(403,'Insufficient review permissions')
    doc=owned(db,core.Document,user.tenant_id,document_id,True);state,version,_reason=review_state(db,doc)
    if data.state=='approved':
        binding_table=core.Base.metadata.tables.get('file_document_subjects')
        binding=db.execute(select(binding_table).where(binding_table.c.document_id==doc.id,binding_table.c.tenant_id==user.tenant_id)).first() if binding_table is not None else None
        if binding is not None and not db.scalar(select(DocumentFileVersion.id).where(DocumentFileVersion.tenant_id==user.tenant_id,DocumentFileVersion.document_id==doc.id).limit(1)):
            raise HTTPException(409,'Adjunta un archivo analizado antes de aprobar este documento.')
    transitions={'pending':{'received'},'received':{'in_review'},'in_review':{'approved','observed','rejected'},'observed':{'received'},'rejected':{'received'},'approved':{'in_review'}}
    if version!=data.expected_version:raise HTTPException(409,'Document review changed; refresh')
    if data.state not in transitions[state]:raise HTTPException(409,'Invalid review transition')
    if data.state in {'observed','rejected'} and len(data.reason.strip())<5:raise HTTPException(422,'A reason is required')
    row=db.scalar(select(Review).where(Review.tenant_id==user.tenant_id,Review.document_id==doc.id))
    if row is None:row=Review(tenant_id=user.tenant_id,document_id=doc.id,updated_by=user.id,fingerprint=fingerprint(db,doc));db.add(row)
    row.state=data.state;row.version=version+1;row.reason=data.reason.strip();row.fingerprint=fingerprint(db,doc);row.updated_by=user.id;row.updated_at=now()
    db.add(ReviewEvent(tenant_id=user.tenant_id,document_id=doc.id,user_id=user.id,state=data.state,version=row.version,reason=row.reason))
    core.add_audit(db,user,'document.review_'+data.state,'document',doc.id);commit(db)
    return {'document_id':doc.id,'state':row.state,'version':row.version}


@core.app.get('/ops/documents/{document_id}/reviews')
def review_history(document_id:int,user:DocRead,db:core.Db):
    _document_for_tenant(db,user.tenant_id,document_id)
    return [{'state':r.state,'version':r.version,'reason':r.reason,'user_id':r.user_id,'at':r.at} for r in db.scalars(select(ReviewEvent).where(ReviewEvent.tenant_id==user.tenant_id,ReviewEvent.document_id==document_id).order_by(ReviewEvent.id.desc())).all()]


class TaskIn(OpsInput):
    title:str=Field(min_length=3,max_length=200)
    assignee_id:int=Field(gt=0)
    service_id:int|None=Field(default=None,gt=0)
    document_id:int|None=Field(default=None,gt=0)
    due_on:date


class TaskUpdate(OpsInput):
    status:str=Field(pattern='^(open|in_progress|done)$')
    expected_version:int=Field(ge=1)


def task_query(user):
    q=select(Task).where(Task.tenant_id==user.tenant_id)
    if user.role!='admin':q=q.where(Task.assignee_id==user.id)
    if 'documents.read' not in capabilities(user.role):q=q.where(Task.document_id.is_(None))
    return q


def task_payload(t):
    return {k:getattr(t,k) for k in ('id','title','assignee_id','service_id','document_id','due_on','status','version')}


@core.app.get('/ops/tasks')
def tasks(user:core.Auth,db:core.Db):
    return [task_payload(t) for t in db.scalars(task_query(user).order_by(Task.due_on,Task.id)).all()]


@core.app.post('/ops/tasks',status_code=201)
def add_task(data:TaskIn,user:TaskWrite,_:core.Csrf,db:core.Db):
    assignee=owned(db,core.User,user.tenant_id,data.assignee_id)
    if not assignee.active:raise HTTPException(409,'Assignee inactive')
    if user.role!='admin' and assignee.id!=user.id:raise HTTPException(403,'Only admin can assign another user')
    if data.service_id is not None:
        service=owned(db,Service,user.tenant_id,data.service_id,True)
        if service.status in {'completed','cancelled'}:raise HTTPException(409,'Service is closed')
    if data.document_id is not None:
        if 'documents.read' not in capabilities(user.role) or 'documents.read' not in capabilities(assignee.role):raise HTTPException(403,'Document access required')
        _document_for_tenant(db,user.tenant_id,data.document_id)
    t=Task(tenant_id=user.tenant_id,**data.model_dump());db.add(t);db.flush();core.add_audit(db,user,'task.create','task',t.id);commit(db);return task_payload(t)


@core.app.patch('/ops/tasks/{task_id}')
def update_task(task_id:int,data:TaskUpdate,user:TaskWrite,_:core.Csrf,db:core.Db):
    t=db.scalar(task_query(user).where(Task.id==task_id).with_for_update())
    if t is None:raise HTTPException(404,'Task not found')
    if t.version!=data.expected_version:raise HTTPException(409,'Task changed; refresh')
    if t.service_id is not None:
        service=owned(db,Service,user.tenant_id,t.service_id,True)
        if service.status=='completed' and data.status!='done':raise HTTPException(409,'Service is closed')
    t.status=data.status;t.version+=1;core.add_audit(db,user,'task.'+data.status,'task',t.id);commit(db);return task_payload(t)


def closeout_data(db,user,service):
    if service.status=='completed' and service.closure_json:
        return json.loads(service.closure_json)
    worker_ids=set(db.scalars(select(Assignment.worker_id).where(Assignment.tenant_id==user.tenant_id,Assignment.service_id==service.id,Assignment.state=='terrain')).all())
    readiness=[worker_readiness(db,user.tenant_id,w,service.project_id) for w in sorted(worker_ids)]
    open_tasks=db.scalar(select(func.count(Task.id)).where(Task.tenant_id==user.tenant_id,Task.service_id==service.id,Task.status!='done')) or 0
    pending_actual=db.scalar(select(func.count(Assignment.id)).where(Assignment.tenant_id==user.tenant_id,Assignment.service_id==service.id,Assignment.state=='terrain',Assignment.actual=='pending')) or 0
    company_requirements=db.scalars(select(Requirement).join(ProjectRequirement,ProjectRequirement.requirement_id==Requirement.id).where(ProjectRequirement.tenant_id==user.tenant_id,ProjectRequirement.project_id==service.project_id,Requirement.tenant_id==user.tenant_id,Requirement.active==1,Requirement.required==1,Requirement.subject_type.in_(['company','project','vehicle']))).all()
    other_missing=[]
    for req in company_requirements:
        docs=db.scalars(select(core.Document).join(DocumentPolicy,DocumentPolicy.document_id==core.Document.id).where(core.Document.tenant_id==user.tenant_id,core.Document.project_id==service.project_id,DocumentPolicy.tenant_id==user.tenant_id,DocumentPolicy.requirement_id==req.id)).all()
        # Vehicles need explicit service association before completeness can be certified.
        if req.subject_type=='vehicle' or not any(evidence_valid(db,d) for d in docs):other_missing.append(req.id)
    ready=bool(worker_ids) and all(r['ready'] for r in readiness) and not other_missing and not open_tasks and not pending_actual and service.ends_on<=date.today()
    return {'service_id':service.id,'ready_to_close':ready,'workers':readiness,'open_tasks':open_tasks,'pending_attendance':pending_actual,'other_blocking_requirements':other_missing,'generated_at':now(),'binary_evidence_required':True}


@core.app.get('/ops/services/{service_id}/closeout')
def closeout(service_id:int,user:DocRead,db:core.Db):
    service=owned(db,Service,user.tenant_id,service_id)
    return closeout_data(db,user,service)


class CloseIn(OpsInput):
    expected_version:int=Field(ge=1)


@core.app.post('/ops/services/{service_id}/close')
def close_service(service_id:int,data:CloseIn,user:core.AdminWrite,db:core.Db):
    service=owned(db,Service,user.tenant_id,service_id,True)
    if service.version!=data.expected_version:raise HTTPException(409,'Service changed')
    owned(db,core.Project,user.tenant_id,service.project_id,True)
    db.scalars(select(core.Document).where(core.Document.tenant_id==user.tenant_id,core.Document.project_id==service.project_id).order_by(core.Document.id).with_for_update()).all()
    report=closeout_data(db,user,service)
    if not report['ready_to_close']:raise HTTPException(409,'Closeout has unresolved requirements, attendance or tasks')
    service.closure_json=json.dumps(report,default=str);service.closed_by=user.id;service.closed_at=now()
    service.status='completed';service.version+=1;core.add_audit(db,user,'service.close','service',service.id);commit(db);return service_payload(service)


@core.app.get('/ops/dashboard')
def dashboard(user:core.Auth,db:core.Db):
    services=db.scalars(select(Service).where(Service.tenant_id==user.tenant_id,Service.status.in_(['scheduled','active']))).all()
    task_rows=db.scalars(task_query(user).where(Task.status!='done')).all()
    tomorrow=date.today()+timedelta(days=1)
    terrain=db.scalars(select(Assignment).where(Assignment.tenant_id==user.tenant_id,Assignment.work_date==tomorrow,Assignment.state=='terrain')).all()
    blocking=0
    for a in terrain:
        s=owned(db,Service,user.tenant_id,a.service_id)
        if not worker_readiness(db,user.tenant_id,a.worker_id,s.project_id,tomorrow)['ready']:blocking+=1
    return {'active_services':len(services),'pending_tasks':len(task_rows),'overdue_tasks':sum(t.due_on<date.today() for t in task_rows),'tomorrow_assignments':len(terrain),'tomorrow_blocked':blocking,'basis':'server_records','generated_at':now()}

class OperationalDocumentIn(OpsInput):
    project_id:int=Field(gt=0)
    worker_id:int=Field(gt=0)
    requirement_id:int=Field(gt=0)
    title:str=Field(min_length=2,max_length=200)
    expires_on:date|None=None
    issued_on:date|None=None
    @model_validator(mode='after')
    def dates(self):
        if self.issued_on and self.expires_on and self.expires_on<self.issued_on:raise ValueError('Expiry cannot precede issue date')
        return self

@core.app.post('/ops/documents',status_code=201)
def create_operational_document(data:OperationalDocumentIn,user:core.Editor,db:core.Db):
    project=owned(db,core.Project,user.tenant_id,data.project_id,True)
    worker=owned(db,core.Worker,user.tenant_id,data.worker_id)
    req=owned(db,Requirement,user.tenant_id,data.requirement_id)
    if not project.active or not worker.active or not req.active or req.subject_type!='worker':raise HTTPException(422,'Active worker requirement, project and worker required')
    doc=core.Document(tenant_id=user.tenant_id,project_id=project.id,subject_type='worker',subject_name=worker.full_name,title=data.title,expires_on=data.expires_on)
    db.add(doc);db.flush()
    db.add(DocumentPolicy(tenant_id=user.tenant_id,document_id=doc.id,requirement_id=req.id,issued_on=data.issued_on))
    db.add(WorkerEvidence(tenant_id=user.tenant_id,worker_id=worker.id,document_id=doc.id))
    core.add_audit(db,user,'document.create','document',doc.id);commit(db)
    return {'id':doc.id,'state':'pending','file_upload_enabled':False}

@core.app.get('/ops/project-requirements')
def project_requirements(user:DocRead,db:core.Db):
    return [{'project_id':r.project_id,'requirement_id':r.requirement_id} for r in db.scalars(select(ProjectRequirement).where(ProjectRequirement.tenant_id==user.tenant_id)).all()]

class RoleIn(OpsInput):
    role:str=Field(pattern='^(admin|editor|viewer|planner|reviewer)$')

@core.app.patch('/users/{user_id}/role')
def change_role(user_id:int,data:RoleIn,user:core.AdminWrite,db:core.Db):
    target=owned(db,core.User,user.tenant_id,user_id,True)
    if target.id==user.id:raise HTTPException(409,'Use another administrator to change your own role')
    target.role=data.role;core.revoke_user_sessions(db,target.id);core.add_audit(db,user,'user.role_update','user',target.id);commit(db)
    return {'id':target.id,'role':target.role,'sessions_revoked':True}
