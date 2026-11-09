"""Pine scripts: stored server-side; executed only client-side in a sandboxed web worker."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.deps import CurrentUser, get_engine

router = APIRouter(prefix="/api/pine", tags=["pine"])
VERSION_RE = re.compile(r"^\s*//\s*@version\s*=\s*(5|6)\b", re.MULTILINE)
MAX_SCRIPTS = 100


class ScriptIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=10, max_length=100_000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name required")
        return v

    @field_validator("source")
    @classmethod
    def _source(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("invalid characters")
        if not VERSION_RE.search(v):
            raise ValueError("script must declare //@version=5 or //@version=6")
        return v.replace("\r\n", "\n")


def _row(r: object) -> dict[str, object]:
    m = dict(r._mapping)  # type: ignore[attr-defined]
    m["created_at"] = m["created_at"].isoformat()
    m["updated_at"] = m["updated_at"].isoformat()
    return m


@router.get("/scripts")
async def list_scripts(
    _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, name, source, builtin, created_at, updated_at FROM pine_script "
                "ORDER BY builtin DESC, name"
            )
        )
        return {"scripts": [_row(r) for r in rows]}


@router.post("/scripts", status_code=status.HTTP_201_CREATED)
async def create_script(
    body: ScriptIn, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    try:
        async with engine.begin() as conn:
            if (await conn.scalar(text("SELECT count(*) FROM pine_script")) or 0) >= MAX_SCRIPTS:
                raise HTTPException(status.HTTP_409_CONFLICT, f"max {MAX_SCRIPTS} scripts")
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO pine_script (name, source) VALUES (:n, :s) "
                        "RETURNING id, name, source, builtin, created_at, updated_at"
                    ),
                    {"n": body.name, "s": body.source},
                )
            ).first()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "name already exists") from exc
    return _row(row)


@router.put("/scripts/{script_id}")
async def update_script(
    script_id: int, body: ScriptIn, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> dict[str, object]:
    try:
        async with engine.begin() as conn:
            builtin = await conn.scalar(
                text("SELECT builtin FROM pine_script WHERE id = :id"), {"id": script_id}
            )
            if builtin is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "script not found")
            if builtin:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "built-in scripts are read-only (duplicate them)"
                )
            row = (
                await conn.execute(
                    text(
                        "UPDATE pine_script SET name = :n, source = :s, updated_at = now() WHERE id = :id "
                        "RETURNING id, name, source, builtin, created_at, updated_at"
                    ),
                    {"n": body.name, "s": body.source, "id": script_id},
                )
            ).first()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "name already exists") from exc
    return _row(row)


@router.delete("/scripts/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script(
    script_id: int, _user: CurrentUser, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> None:
    async with engine.begin() as conn:
        builtin = await conn.scalar(text("SELECT builtin FROM pine_script WHERE id = :id"), {"id": script_id})
        if builtin is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "script not found")
        if builtin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "built-in scripts cannot be deleted")
        await conn.execute(text("DELETE FROM pine_script WHERE id = :id"), {"id": script_id})
