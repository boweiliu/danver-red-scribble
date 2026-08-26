"""The two things only the workspace can do: list its chats, and deliver a message to one.

These are the ``list_agents`` / ``deliver`` callbacks :class:`red_scribble.dispatch.RedScribbleDeps`
asks for. They talk to the mngr Python API directly -- the same calls the workspace UI's chat box
makes -- so Red Scribble depends on mngr and on nothing else in the workspace.

Both swallow mngr failures and degrade (an empty agent list, an undelivered message) rather than
raising: a broken chat lookup must not take down the plug-in the user is drawing with.
"""

import time
from collections.abc import Callable
from collections.abc import Sequence
from typing import Final

from loguru import logger
from pydantic import Field

from imbue.concurrency_group.concurrency_group import ConcurrencyGroup
from imbue.imbue_common.mutable_model import MutableModel
from imbue.mngr.api.find import AgentMatch
from imbue.mngr.api.find import find_all_agents
from imbue.mngr.api.list import list_agents
from imbue.mngr.api.message import send_message_to_agents
from imbue.mngr.config.data_types import MngrContext
from imbue.mngr.config.loader import load_config
from imbue.mngr.errors import MngrError
from imbue.mngr.main import get_or_create_plugin_manager
from imbue.mngr.primitives import AgentAddress
from imbue.mngr.primitives import AgentId
from imbue.mngr.primitives import ErrorBehavior

from red_scribble.dispatch import AgentSummary


def _mngr_context() -> tuple[MngrContext, ConcurrencyGroup]:
    concurrency_group = ConcurrencyGroup(name="red-scribble")
    concurrency_group.__enter__()
    try:
        plugin_manager = get_or_create_plugin_manager()
        mngr_ctx = load_config(plugin_manager, concurrency_group, is_interactive=False)
    except BaseException:
        concurrency_group.__exit__(None, None, None)
        raise
    return mngr_ctx, concurrency_group


def list_workspace_agents() -> tuple[AgentSummary, ...]:
    """Every mngr-managed chat, as the plug-in's target-agent menu shows them."""
    try:
        mngr_ctx, concurrency_group = _mngr_context()
    except MngrError as error:
        logger.warning("Failed to load the mngr context while listing chats: {}", error)
        return ()
    try:
        result = list_agents(
            mngr_ctx=mngr_ctx,
            is_streaming=False,
            include_filters=(),
            exclude_filters=(),
            provider_names=None,
            error_behavior=ErrorBehavior.CONTINUE,
        )
    except MngrError as error:
        logger.warning("Failed to list chats for the Red Scribble menu: {}", error)
        return ()
    finally:
        concurrency_group.__exit__(None, None, None)

    return tuple(
        AgentSummary(
            id=str(details.id),
            name=str(details.name),
            state=str(details.state.value) if details.state else "unknown",
        )
        for details in result.agents
    )


# How long a chat list stays fresh. Listing is expensive -- it loads the mngr context and walks
# every provider -- and the plug-in asks for it on load and again on every menu open, while the
# set of chats changes on a human timescale.
AGENT_LIST_FRESHNESS_SECONDS: Final[float] = 30.0


class CachedAgentList(MutableModel):
    """Holds the workspace's chat list briefly, so opening the menu is not a full discovery."""

    load: Callable[[], tuple[AgentSummary, ...]] = Field(
        default=list_workspace_agents, description="How to fetch the list when it is stale"
    )
    freshness_seconds: float = Field(
        default=AGENT_LIST_FRESHNESS_SECONDS, description="How long a fetched list stays usable"
    )
    agents: tuple[AgentSummary, ...] = Field(default=(), description="The most recent list")
    fetched_at: float | None = Field(default=None, description="Monotonic time of that fetch")

    def get(self) -> tuple[AgentSummary, ...]:
        now = time.monotonic()
        if self.fetched_at is not None and now - self.fetched_at < self.freshness_seconds:
            return self.agents
        self.agents = self.load()
        self.fetched_at = now
        return self.agents


def _resolve(agent_id: str, mngr_ctx: MngrContext) -> Sequence[AgentMatch]:
    return find_all_agents(
        addresses=(AgentAddress(agent=AgentId(agent_id)),),
        filter_all=False,
        target_state=None,
        mngr_ctx=mngr_ctx,
    )


def deliver_to_agent(agent_id: str, message: str) -> bool:
    """Hand one message to a chat's agent, starting it if it is stopped.

    The id is globally unique, so this resolves to exactly the chat the user picked. Returns
    whether the message actually reached an agent.
    """
    try:
        mngr_ctx, concurrency_group = _mngr_context()
    except MngrError as error:
        logger.warning("Failed to load the mngr context while delivering feedback: {}", error)
        return False
    try:
        matches = _resolve(agent_id, mngr_ctx)
        result = send_message_to_agents(
            mngr_ctx=mngr_ctx,
            message_content=message,
            agents_to_message=matches,
            error_behavior=ErrorBehavior.CONTINUE,
            is_start_desired=True,
        )
    except MngrError as error:
        logger.warning("Failed to deliver Red Scribble feedback to {}: {}", agent_id, error)
        return False
    finally:
        concurrency_group.__exit__(None, None, None)
    return bool(result.successful_agents)
