"""Run with the account operator's AWS credentials after approving the included policy.
Creates a new private bucket and an upload-only principal; never prints access keys.
"""
import argparse,json,os,subprocess
from pathlib import Path

def run(plan_path,certificate,output):
    import boto3
    os.umask(0o077)
    p=json.loads(Path(plan_path).read_text());session=boto3.Session(region_name=p['region']);s3=session.client('s3');iam=session.client('iam')
    account=session.client('sts').get_caller_identity()['Account'];assert account=='000000000000'
    # Fresh named resources only. Existing names require explicit review instead of replacement.
    if any(b['Name']==p['bucket'] for b in s3.list_buckets()['Buckets']):raise RuntimeError('bucket_already_exists_review_required')
    try:iam.get_user(UserName=p['writer_user'])
    except iam.exceptions.NoSuchEntityException:pass
    else:raise RuntimeError('writer_already_exists_review_required')
    s3.create_bucket(Bucket=p['bucket'],CreateBucketConfiguration={'LocationConstraint':p['region']},ObjectOwnership='BucketOwnerEnforced')
    s3.put_public_access_block(Bucket=p['bucket'],PublicAccessBlockConfiguration=p['public_access_block'])
    s3.put_bucket_encryption(Bucket=p['bucket'],ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
    s3.put_bucket_versioning(Bucket=p['bucket'],VersioningConfiguration={'Status':'Enabled'})
    policy={'Version':'2012-10-17','Statement':[{'Sid':'DenyInsecureTransport','Effect':'Deny','Principal':'*','Action':'s3:*','Resource':['arn:aws:s3:::'+p['bucket'],'arn:aws:s3:::'+p['bucket']+'/*'],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}
    s3.put_bucket_policy(Bucket=p['bucket'],Policy=json.dumps(policy));s3.put_bucket_lifecycle_configuration(Bucket=p['bucket'],LifecycleConfiguration=p['lifecycle'])
    s3.put_bucket_tagging(Bucket=p['bucket'],Tagging={'TagSet':[{'Key':'Purpose','Value':'KiwoomEncryptedDatabaseBackup'}]})
    iam.create_user(UserName=p['writer_user'],Tags=[{'Key':'Purpose','Value':'KiwoomBackupWriteOnly'}])
    iam.put_user_policy(UserName=p['writer_user'],PolicyName='UploadOnlyEncryptedDatabaseBackups',PolicyDocument=json.dumps(p['writer_policy']))
    key=iam.create_access_key(UserName=p['writer_user'])['AccessKey']
    output=Path(output);output.mkdir(mode=0o700,parents=True,exist_ok=True)
    private=output/'writer-credentials.json';private.write_text(json.dumps({'access_key_id':key['AccessKeyId'],'secret_access_key':key['SecretAccessKey']}));private.chmod(0o600)
    subprocess.run(['openssl','cms','-encrypt','-binary','-aes-256-gcm','-outform','DER','-in',str(private),'-out',str(output/'writer-credentials.cms'),str(certificate)],check=True)
    cw=session.client('cloudwatch')
    cw.put_metric_alarm(AlarmName='KiwoomDatabaseBackupMissing',AlarmDescription='Trading DB backup failed or missing for one daily period. No automatic trading actions.',Namespace='Kiwoom/Backup',MetricName='BackupSuccess',Dimensions=[{'Name':'Instance','Value':'example-server'}],Statistic='Minimum',Period=86400,EvaluationPeriods=1,DatapointsToAlarm=1,Threshold=1,ComparisonOperator='LessThanThreshold',TreatMissingData='breaching',ActionsEnabled=False)
    result={'bucket':p['bucket'],'region':p['region'],'public_access_block':s3.get_public_access_block(Bucket=p['bucket'])['PublicAccessBlockConfiguration'],'versioning':s3.get_bucket_versioning(Bucket=p['bucket'])['Status'],'encryption':s3.get_bucket_encryption(Bucket=p['bucket'])['ServerSideEncryptionConfiguration'],'writer_user':p['writer_user'],'alarm':'KiwoomDatabaseBackupMissing'}
    (output/'provision-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    # The encrypted handoff is sufficient; remove only this transient generated secret copy.
    private.unlink()
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--plan',required=True);a.add_argument('--certificate',required=True);a.add_argument('--output',required=True);v=a.parse_args();run(v.plan,v.certificate,v.output)
