"""PBKDF2-SHA256 credentials and hashed, persistent login tokens."""
import base64,hmac,hashlib,secrets

def hash_password(password):
    if not isinstance(password,str) or len(password)<12:
        raise ValueError('Passwort benötigt mindestens 12 Zeichen')
    salt=secrets.token_bytes(16)
    iterations=600_000
    dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,iterations)
    return 'pbkdf2_sha256$%s$%s$%s'%(iterations,base64.urlsafe_b64encode(salt).decode(),base64.urlsafe_b64encode(dk).decode())

def verify_password(password, stored):
    try:
        method,n,salt,digest=stored.split('$')
        if method!='pbkdf2_sha256':return False
        result=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.urlsafe_b64decode(salt),int(n))
        return hmac.compare_digest(result,base64.urlsafe_b64decode(digest))
    except (ValueError,TypeError):return False

def token_pair():
    raw=secrets.token_urlsafe(32)
    return raw,hashlib.sha256(raw.encode()).hexdigest()

def token_digest(raw):return hashlib.sha256(raw.encode()).hexdigest()
