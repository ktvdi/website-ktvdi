from __future__ import annotations
from firebase_admin import db

def _public_user(username, user):
    return {"username":username,"nama":user.get("nama",username),"points":user.get("points",0),
        **{k:user.get(k,"") for k in ("provinsi","wilayah","tv_brand","stb_brand","antenna_brand")}}


def _all_reports():
    data=db.reference("broadcast_reports").get() or {}
    return [{"id":k,**v} for k,v in data.items() if isinstance(v,dict)]


def _all_users_public():
    users=db.reference("users").get() or {}
    return [_public_user(k,v) for k,v in users.items() if isinstance(v,dict)]


def _profile(username):
    data=db.reference(f"users/{username}").get() or {}
    return _public_user(username,data)


def _comments(prov, area, mux):
    data=db.reference(f"siaran/{prov}/{area}/{mux}/comments").get() or {}
    return [{"id":k,**v} for k,v in sorted(data.items(),key=lambda kv:kv[1].get("timestamp",""),reverse=True) if isinstance(v,dict)]
