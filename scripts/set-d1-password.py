"""Owner-only local password configuration; never prints the password or its hash."""
import argparse,getpass,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.d1_identity import D1Store,configuration
from backend.security import password_hash,validate_password

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--user-id',type=int,required=True);args=parser.parse_args()
    if args.user_id<10001:raise SystemExit('用户编号必须从10001开始')
    password=getpass.getpass('输入你为该账号设置的新密码：')
    if password!=getpass.getpass('再次输入密码：'):raise SystemExit('两次密码不一致，未修改')
    validate_password(password)
    store=D1Store(configuration());revision,rows=store.snapshot()
    if not any(str(row['user_id'])==str(args.user_id) for row in rows['auth_users']):raise SystemExit('账号不存在，未修改')
    store.commit(revision,[{'sql':'UPDATE auth_users SET password_hash=?,version=version+1 WHERE user_id=?','params':[password_hash(password),args.user_id]},
                           {'sql':'DELETE FROM auth_sessions WHERE user_id=?','params':[args.user_id]}])
    password=None
    print('密码已更新，旧会话已失效；未输出密码或哈希。')

if __name__=='__main__':main()
