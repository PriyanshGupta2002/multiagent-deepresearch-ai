import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.db.dependencies import get_db
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.research.models import ResearchJob, ResearchReport
from app.modules.saved_reports.models import SavedReport


@pytest_asyncio.fixture
async def api_client(test_session_factory):
    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def research_factory(test_session_factory):
    user_ids: set[str] = set()
    research_ids: set[str] = set()

    async def create(
        query: str = "A research query",
        depth: str = "standard",
        research_status: str = "completed",
        report_content: str | None = None,
        create_report: bool = True,
        user: User | None = None,
    ):
        if user is None:
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                email=f"{user_id}@example.test",
                full_name="Saved report test",
                hashed_password="unused",
            )
            user_ids.add(user_id)
            create_user = True
        else:
            create_user = False

        research_id = str(uuid.uuid4())
        research_ids.add(research_id)
        async with test_session_factory() as session:
            if create_user:
                session.add(user)
            session.add(
                ResearchJob(
                    id=research_id,
                    user_id=user.id,
                    query=query,
                    depth=depth,
                    status=research_status,
                )
            )
            if create_report:
                session.add(
                    ResearchReport(
                        research_id=research_id,
                        content=report_content or f"Actual report content for {query}",
                    )
                )
            await session.commit()
        return user, research_id

    yield create

    async with test_session_factory() as session:
        if research_ids:
            await session.execute(
                delete(SavedReport).where(
                    SavedReport.research_id.in_(research_ids)
                )
            )
            await session.execute(
                delete(ResearchReport).where(
                    ResearchReport.research_id.in_(research_ids)
                )
            )
            await session.execute(
                delete(ResearchJob).where(ResearchJob.id.in_(research_ids))
            )
        if user_ids:
            await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def _authenticate_as(user: User) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.asyncio
async def test_save_completed_report(api_client, research_factory):
    user, research_id = await research_factory(
        query="Evidence about coastal restoration",
        depth="comprehensive",
        report_content="The report's actual opening paragraph.",
    )
    _authenticate_as(user)

    response = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": research_id},
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "research_id",
        "query",
        "depth",
        "report_created_at",
        "saved_at",
    }
    assert body["research_id"] == research_id
    assert body["query"] == "Evidence about coastal restoration"
    assert body["depth"] == "comprehensive"
    assert body["report_created_at"]
    assert body["saved_at"]


@pytest.mark.asyncio
async def test_saving_same_report_is_idempotent(
    api_client,
    research_factory,
    test_session,
):
    user, research_id = await research_factory()
    _authenticate_as(user)

    first = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": research_id},
    )
    second = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": research_id},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    count = await test_session.scalar(
        select(func.count(SavedReport.id)).where(
            SavedReport.user_id == user.id,
            SavedReport.research_id == research_id,
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_saves_create_one_association(
    api_client,
    research_factory,
    test_session,
):
    user, research_id = await research_factory()
    _authenticate_as(user)

    responses = await asyncio.gather(
        *(
            api_client.post(
                "/api/v1/saved-reports",
                json={"research_id": research_id},
            )
            for _ in range(2)
        )
    )

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    count = await test_session.scalar(
        select(func.count(SavedReport.id)).where(
            SavedReport.user_id == user.id,
            SavedReport.research_id == research_id,
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_cannot_save_report_before_it_is_generated(
    api_client,
    research_factory,
):
    user, research_id = await research_factory(create_report=False)
    _authenticate_as(user)

    response = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": research_id},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "RESEARCH_REPORT_NOT_GENERATED"


@pytest.mark.asyncio
async def test_cannot_save_another_users_research(
    api_client,
    research_factory,
):
    requester, _ = await research_factory()
    _, other_research_id = await research_factory()
    _authenticate_as(requester)

    response = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": other_research_id},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "RESEARCH_NOT_FOUND"


@pytest.mark.asyncio
async def test_save_requires_completed_research(api_client, research_factory):
    user, research_id = await research_factory(research_status="running")
    _authenticate_as(user)

    response = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": research_id},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "RESEARCH_NOT_COMPLETED"


@pytest.mark.asyncio
async def test_list_paginates_and_filters_by_search_and_depth(
    api_client,
    research_factory,
):
    user, first_id = await research_factory(
        query="Ocean restoration overview",
        depth="quick",
        report_content="First report excerpt.",
    )
    _, second_id = await research_factory(
        query="Ocean restoration funding",
        depth="comprehensive",
        report_content="Second report excerpt.",
        user=user,
    )
    _, third_id = await research_factory(
        query="Mountain biodiversity",
        depth="standard",
        report_content="Third report excerpt.",
        user=user,
    )
    _authenticate_as(user)

    for research_id in (first_id, second_id, third_id):
        response = await api_client.post(
            "/api/v1/saved-reports",
            json={"research_id": research_id},
        )
        assert response.status_code == 201

    page_response = await api_client.get(
        "/api/v1/saved-reports",
        params={"page": 2, "limit": 2},
    )
    page = page_response.json()
    assert page_response.status_code == 200
    assert page["total"] == 3
    assert page["page"] == 2
    assert page["limit"] == 2
    assert page["total_pages"] == 2
    assert page["has_more"] is False
    assert len(page["items"]) == 1

    search_response = await api_client.get(
        "/api/v1/saved-reports",
        params={"search": "Ocean restoration", "depth": "quick"},
    )
    search_result = search_response.json()
    assert search_response.status_code == 200
    assert search_result["total"] == 1
    assert search_result["items"][0]["research_id"] == first_id
    assert search_result["items"][0]["report_preview"] == "First report excerpt."

    recent_response = await api_client.get("/api/v1/saved-reports")
    saved_at_values = [item["saved_at"] for item in recent_response.json()["items"]]
    assert saved_at_values == sorted(saved_at_values, reverse=True)


@pytest.mark.asyncio
async def test_status_and_library_are_isolated_between_users(
    api_client,
    research_factory,
):
    first_user, first_research_id = await research_factory()
    second_user, second_research_id = await research_factory()

    _authenticate_as(first_user)
    assert (
        await api_client.post(
            "/api/v1/saved-reports",
            json={"research_id": first_research_id},
        )
    ).status_code == 201

    _authenticate_as(second_user)
    assert (
        await api_client.post(
            "/api/v1/saved-reports",
            json={"research_id": second_research_id},
        )
    ).status_code == 201

    _authenticate_as(first_user)
    own_status = await api_client.get(
        f"/api/v1/saved-reports/{first_research_id}/status"
    )
    other_status = await api_client.get(
        f"/api/v1/saved-reports/{second_research_id}/status"
    )
    listing = await api_client.get("/api/v1/saved-reports")

    assert own_status.json() == {
        "research_id": first_research_id,
        "is_saved": True,
    }
    assert other_status.json() == {
        "research_id": second_research_id,
        "is_saved": False,
    }
    assert [
        item["research_id"] for item in listing.json()["items"]
    ] == [first_research_id]


@pytest.mark.asyncio
async def test_unsaving_is_idempotent_and_preserves_research_and_report(
    api_client,
    research_factory,
    test_session,
):
    user, research_id = await research_factory(
        report_content="Original report remains intact."
    )
    _authenticate_as(user)
    assert (
        await api_client.post(
            "/api/v1/saved-reports",
            json={"research_id": research_id},
        )
    ).status_code == 201

    first_delete = await api_client.delete(
        f"/api/v1/saved-reports/{research_id}"
    )
    second_delete = await api_client.delete(
        f"/api/v1/saved-reports/{research_id}"
    )

    assert first_delete.status_code == second_delete.status_code == 200
    assert first_delete.json() == {
        "success": True,
        "research_id": research_id,
        "is_saved": False,
    }
    assert second_delete.json() == first_delete.json()
    assert await test_session.get(ResearchJob, research_id) is not None
    report = await test_session.scalar(
        select(ResearchReport).where(ResearchReport.research_id == research_id)
    )
    assert report is not None
    assert report.content == "Original report remains intact."


@pytest.mark.asyncio
async def test_invalid_save_request_returns_validation_error(
    api_client,
    research_factory,
):
    user, _ = await research_factory()
    _authenticate_as(user)

    response = await api_client.post(
        "/api/v1/saved-reports",
        json={"research_id": "not-a-uuid"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_all_saved_report_endpoints_require_authentication(api_client):
    research_id = str(uuid.uuid4())
    responses = await asyncio.gather(
        api_client.get("/api/v1/saved-reports"),
        api_client.post(
            "/api/v1/saved-reports",
            json={"research_id": research_id},
        ),
        api_client.get(f"/api/v1/saved-reports/{research_id}/status"),
        api_client.delete(f"/api/v1/saved-reports/{research_id}"),
    )

    assert [response.status_code for response in responses] == [
        401,
        401,
        401,
        401,
    ]
