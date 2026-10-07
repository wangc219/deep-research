import pytest
from pydantic import ValidationError

from server.routers.auth_dept_router import DepartmentCreate
from server.routers.auth_router import InitializeAdmin, PublicUserRegister, UserCreate, UserUpdate


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (InitializeAdmin, {"uid": "admin", "password": "short"}),
        (UserCreate, {"username": "user", "password": "short"}),
        (UserUpdate, {"password": "short"}),
        (
            DepartmentCreate,
            {
                "name": "department",
                "admin_uid": "admin",
                "admin_password": "short",
            },
        ),
    ],
)
def test_admin_password_models_reject_passwords_shorter_than_eight_characters(model, payload):
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(payload)

    assert exc_info.value.errors()[0]["type"] == "string_too_short"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (InitializeAdmin, {"uid": "admin", "password": "12345678"}),
        (UserCreate, {"username": "user", "password": "12345678"}),
        (UserUpdate, {"password": "12345678"}),
        (
            DepartmentCreate,
            {
                "name": "department",
                "admin_uid": "admin",
                "admin_password": "12345678",
            },
        ),
    ],
)
def test_admin_password_models_accept_eight_character_passwords(model, payload):
    assert model.model_validate(payload)


def test_user_update_allows_password_to_be_omitted():
    assert UserUpdate().password is None


def test_department_create_allows_admin_to_be_omitted():
    department = DepartmentCreate(name="department")

    assert department.admin_uid is None
    assert department.admin_password is None


@pytest.mark.parametrize("role", ["superadmin", "admin", "user"])
def test_user_management_models_accept_known_roles(role):
    assert UserCreate(username="user", password="12345678", role=role).role == role
    assert UserUpdate(role=role).role == role


@pytest.mark.parametrize("model", [UserCreate, UserUpdate])
def test_user_management_models_reject_unknown_roles(model):
    payload = {"role": "owner"}
    if model is UserCreate:
        payload.update(username="user", password="12345678")

    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(payload)

    assert exc_info.value.errors()[0]["type"] == "literal_error"


def test_public_registration_rejects_role_injection():
    with pytest.raises(ValidationError) as exc_info:
        PublicUserRegister.model_validate(
            {
                "username": "ordinary-user",
                "password": "12345678",
                "role": "superadmin",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
