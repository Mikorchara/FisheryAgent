"""Explicit local migration. Dry-run by default, no model/credential access."""
import argparse
import json
from pathlib import Path
from .migration import migrate, backup
from .repository import KnowledgeError


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description='统一知识库迁移；先关闭管理服务器，备份并创建新库，不覆盖旧库。')
    parser.add_argument('--source',type=Path,default=root/'outputs/management_web/knowledge.sqlite3')
    parser.add_argument('--target',type=Path,default=root/'apps/knowledge_data/knowledge.sqlite3')
    parser.add_argument('--legacy-json',type=Path,default=root/'src/fishery_ai/resources/knowledge/eel_knowledge.json')
    parser.add_argument('--without-user-db',action='store_true',help='仅首次安装且没有旧用户库时使用；不迁入用户条目')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--apply',action='store_true')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--backup-to',type=Path,help='只备份统一库到新文件；需 --apply，不覆盖任何文件')
    args=parser.parse_args()
    if args.without_user_db and args.source.is_file():
        parser.error('已有旧知识库，不能使用 --without-user-db 跳过用户数据')
    try:
        if args.backup_to:
            if not args.apply or args.plan_sha256 or args.without_user_db:
                parser.error('备份仅使用 --backup-to 新文件路径 --apply')
            result=backup(args.target,args.backup_to)
        else:
            result=migrate(None if args.without_user_db else args.source,args.target,args.legacy_json,
                           apply=args.apply,approved_plan_sha256=args.plan_sha256)
    except KnowledgeError as error:
        print(json.dumps({'status':'failed','error_code':error.code}));return 1
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
