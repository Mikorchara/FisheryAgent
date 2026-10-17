"""Child-process fixture: real management/ingestion, temporary SQLite, no AI."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    service=MonitoringService(MonitoringRepository(Path(args.directory)/'isolated.sqlite3'))
    create_app(data_service=service,ingestion_token=os.environ['FISHERY_SIM_INGEST_TOKEN'],
        allowed_hosts=(f'127.0.0.1:{args.port}',)).run(host='127.0.0.1',port=args.port,load_dotenv=False)
