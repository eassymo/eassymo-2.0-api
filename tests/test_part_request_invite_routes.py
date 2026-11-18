"""Part request invite routes must not redirect on a trailing slash."""

from starlette.routing import Match

from app.routers.PartRequestInviteRouter import partRequestInviteRouter


def test_update_status_answers_with_and_without_trailing_slash():
    # A redirect from ".../update-status/" makes browsers drop the Authorization header,
    # the retry gets 401 and the client logs the user out. Both spellings must match directly.
    for path in ("/partRequestInvite/update-status", "/partRequestInvite/update-status/"):
        scope = {"type": "http", "method": "PUT", "path": path}
        matched = [r for r in partRequestInviteRouter.routes if r.matches(scope)[0] == Match.FULL]
        assert matched and matched[0].endpoint.__name__ == "update_status", path
