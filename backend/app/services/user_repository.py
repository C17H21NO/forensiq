from typing import Optional
from sqlalchemy.orm import Session

from app.models import UserDB
from app.services.auth_service import hash_password


def get_user_by_username(db: Session, username: str) -> Optional[UserDB]:
    return db.query(UserDB).filter(UserDB.username == username.lower().strip()).first()

def update_user_password_hash(
    db: Session,
    user: UserDB,
    new_password_hash: str,
) -> UserDB:
    """
    Actualiza únicamente el hash de contraseña de un usuario existente.

    Se utiliza para migrar transparentemente hashes TP1 a PBKDF2
    después de un login exitoso.
    """

    user.password_hash = new_password_hash

    db.add(user)
    db.commit()
    db.refresh(user)

    return user

def create_user(
    db: Session,
    username: str,
    full_name: str,
    role: str,
    password: str,
) -> UserDB:
    clean_username = username.lower().strip()
    role = role.upper().strip()

    user = UserDB(
        username=clean_username,
        full_name=full_name.strip(),
        role=role,

        # Aunque se conserve clean_username como segundo argumento
        # por compatibilidad, hash_password ya genera PBKDF2
        # con salt aleatorio.
        password_hash=hash_password(
            password,
            clean_username,
        ),

        is_active=1,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def list_users(db: Session):
    return db.query(UserDB).order_by(UserDB.id.asc()).all()





def serialize_user(user: UserDB):
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": bool(user.is_active),
    }
