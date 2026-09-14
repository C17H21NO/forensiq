import sys
from getpass import getpass
from pathlib import Path

from sqlalchemy.engine import make_url


BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND_ROOT),
    )


from app.config import settings
from app.database import SessionLocal
from app.services.user_repository import (
    create_user,
    get_user_by_username,
)


def main():
    safe_url = make_url(
        settings.database_url
    ).render_as_string(
        hide_password=True
    )

    print("=" * 72)
    print("ForensiQ - Crear ADMIN inicial")
    print(f"Database: {safe_url}")
    print("=" * 72)

    username = input(
        "Email/username ADMIN: "
    ).strip().lower()

    if not username:
        raise SystemExit(
            "El username es obligatorio."
        )

    full_name = input(
        "Nombre completo: "
    ).strip()

    if not full_name:
        raise SystemExit(
            "El nombre completo es obligatorio."
        )

    password = getpass(
        "Contraseña: "
    )

    password_confirm = getpass(
        "Repetir contraseña: "
    )

    if password != password_confirm:
        raise SystemExit(
            "Las contraseñas no coinciden."
        )

    if len(password) < 12:
        raise SystemExit(
            "La contraseña debe tener al menos "
            "12 caracteres."
        )

    db = SessionLocal()

    try:
        existing = get_user_by_username(
            db,
            username,
        )

        if existing is not None:
            raise SystemExit(
                "Ese usuario ya existe."
            )

        user = create_user(
            db=db,
            username=username,
            full_name=full_name,
            role="ADMIN",
            password=password,
        )

        print()
        print(
            "ADMIN creado correctamente:"
        )
        print(
            f"  username: {user.username}"
        )
        print(
            f"  role:     {user.role}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()