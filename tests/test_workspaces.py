"""Workspace validation and API isolation using mocked database sessions."""

from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from search_anything.api import WorkspaceWriteRequest, create_app
from search_anything.models import Asset, IngestionProfile, Workspace
from search_anything.settings import Settings
from search_anything.storage import ObjectRead


@pytest.mark.parametrize("name", ["", " \n\t ", "a" * 161])
def test_workspace_rejects_empty_or_long_names(name):
    with pytest.raises(ValueError):
        WorkspaceWriteRequest(name=name)


def test_workspace_normalizes_name():
    assert WorkspaceWriteRequest(name="  Apollo   11 \n").name == "Apollo 11"


@pytest.fixture
def workspace_app():
    a, b = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    workspaces = {
        ident: Workspace(id=ident, name=name, created_at=now)
        for ident, name in [(a, "Apollo 11"), (b, "Work")]
    }
    asset = Asset(
        id=uuid4(),
        workspace_id=a,
        filename="moon.txt",
        normalized_filename="moon.txt",
        content_type="text/plain",
        byte_size=11,
        content_hash="0" * 64,
        storage_key=f"workspaces/{a}/moon",
        state="ready",
        created_at=now,
    )
    profile = IngestionProfile(
        id=uuid4(),
        workspace_id=a,
        name="automatic",
        revision=1,
        config={},
        created_at=now,
    )
    session = AsyncMock(spec=AsyncSession)
    session.begin = MagicMock(return_value=AsyncMock())
    session.__aenter__.return_value = session

    async def get(model, ident):
        return workspaces.get(ident) if model is Workspace else None

    async def scalar(statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Asset:
            # Interpret the bound ownership predicates rather than returning
            # the fixture regardless of the query the handler actually builds.
            params = statement.compile().params
            assert "workspace_id_1" in params
            assert "id_1" in params
            if (
                params["workspace_id_1"] == asset.workspace_id
                and params["id_1"] == asset.id
            ):
                return asset
            return None
        if entity is IngestionProfile:
            return profile
        return None

    session.get.side_effect = get
    session.scalar.side_effect = scalar

    async def scalars(statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        result = MagicMock()
        if entity is Asset:
            assert "workspace_id_1" in params
            result.all.return_value = [asset] if params["workspace_id_1"] == a else []
        elif entity is IngestionProfile:
            assert "workspace_id_1" in params
            result.all.return_value = [profile] if params["workspace_id_1"] == a else []
        else:
            result.all.return_value = list(workspaces.values())
        return result

    session.scalars.side_effect = scalars

    def add(row):
        row.created_at = now
        if isinstance(row, Workspace):
            workspaces[row.id] = row

    session.add = MagicMock(side_effect=add)
    storage = MagicMock()
    storage.get_object = AsyncMock(
        return_value=ObjectRead(BytesIO(b"moon sample"), 11, "text/plain", None, False)
    )
    storage.presigned_get_url = AsyncMock(return_value="http://mock.test/moon")
    storage.put_file = AsyncMock()
    settings = Settings(_env_file=None, default_workspace_id=a)
    app = create_app(settings, session_factory=lambda: session, storage=storage)
    return app, session, storage, workspaces, asset, a, b


@pytest.mark.asyncio
async def test_cross_workspace_asset_reads_and_actions_are_rejected(workspace_app):
    app, session, storage, _, asset, a, b = workspace_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock.test"
    ) as client:
        for suffix in ["", "/status", "/content", "/presigned"]:
            response = await client.get(
                f"/api/assets/{asset.id}{suffix}", params={"workspace_id": str(b)}
            )
            assert response.status_code == 404, response.text
        for suffix in ["/retry", "/cancel", "/reprocess"]:
            response = await client.post(
                f"/api/assets/{asset.id}{suffix}",
                params={"workspace_id": str(b)},
                json={"profile_name": "automatic"},
            )
            assert response.status_code == 404, response.text
        response = await client.delete(
            f"/api/assets/{asset.id}", params={"workspace_id": str(b)}
        )
        assert response.status_code == 404
        storage.get_object.assert_not_awaited()
        storage.presigned_get_url.assert_not_awaited()
        response = await client.get(
            f"/api/assets/{asset.id}/content", params={"workspace_id": str(a)}
        )
        assert response.content == b"moon sample"
        assert (
            await client.get(
                f"/api/assets/{asset.id}/presigned", params={"workspace_id": str(a)}
            )
        ).status_code == 200
        assert (await client.get("/api/assets?workspace_id=invalid")).status_code == 422
        assert (
            await client.get(f"/api/assets?workspace_id={uuid4()}")
        ).status_code == 404


@pytest.mark.asyncio
async def test_search_enqueues_selected_workspace(workspace_app):
    app, session, _, _, _, a, b = workspace_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock.test"
    ) as client:
        for ident in [a, b]:
            response = await client.post(
                "/api/search",
                params={"workspace_id": str(ident)},
                json={"query": "moon", "mode": "keyword"},
            )
            assert response.status_code == 202, response.text
            job = session.add.call_args.args[0]
            assert job.workspace_id == ident
            assert job.stage == "search"
            assert job.payload["options"]["query"] == "moon"
            assert response.json()["id"] == str(job.id)
            session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_library_and_profile_lists_use_workspace_predicates(workspace_app):
    app, _, _, _, asset, a, b = workspace_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock.test"
    ) as client:
        for ident, expected in [(a, [str(asset.id)]), (b, [])]:
            response = await client.get(
                "/api/assets", params={"workspace_id": str(ident)}
            )
            assert response.status_code == 200
            assert [row["id"] for row in response.json()] == expected
            profiles = await client.get(
                "/api/profiles", params={"workspace_id": str(ident)}
            )
            assert profiles.status_code == 200
            assert len(profiles.json()) == (1 if ident == a else 0)


@pytest.mark.asyncio
async def test_create_rename_and_upload_scope(workspace_app):
    app, session, storage, workspaces, _, _, b = workspace_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock.test"
    ) as client:
        response = await client.post("/api/workspaces", json={"name": "  Research  "})
        assert response.status_code == 201, response.text
        assert response.json()["name"] == "Research"
        workspace_id = response.json()["id"]
        response = await client.patch(
            f"/api/workspaces/{workspace_id}", json={"name": "Research notes"}
        )
        assert response.json()["name"] == "Research notes"
        assert (
            await client.post("/api/workspaces", json={"name": " "})
        ).status_code == 422
        assert (
            await client.patch(f"/api/workspaces/{uuid4()}", json={"name": "Missing"})
        ).status_code == 404
        # Uploads select their profile and storage path from the request.
        response = await client.post(
            "/api/assets",
            params={"workspace_id": str(b)},
            files={"file": ("moon.txt", b"moon sample", "text/plain")},
        )
        assert response.status_code == 201, response.text
        assert storage.put_file.await_args.args[0].startswith(f"workspaces/{b}/assets/")
        added_assets = [
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], Asset)
        ]
        assert added_assets[0].workspace_id == b
        profile_queries = [
            call.args[0]
            for call in session.scalar.await_args_list
            if call.args[0].column_descriptions[0]["entity"] is IngestionProfile
        ]
        assert profile_queries[-1].compile().params["workspace_id_1"] == b
