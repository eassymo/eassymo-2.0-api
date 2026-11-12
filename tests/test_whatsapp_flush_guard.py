from unittest.mock import MagicMock, patch

from app.services.WhatsappSellerIdentityService import NO_ACCESS_MESSAGE
from tests.test_whatsapp_intake import _collecting_session


def _run(mock_identity_cls, entitled):
    from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService

    mock_identity_cls.return_value.is_entitled.return_value = entitled
    session = _collecting_session(
        messages=[{"message_sid": "SM-1", "body": "Jetta 2015 balatas"}],
    )
    service = WhatsappIntakeProcessorService()
    service.extract_enabled = True
    service._flush_session_body("+5217779313704", session)
    return service


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_without_entitlement_sends_no_access_and_skips_model_and_folio(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    mock_inbound_repo.find_by_message_sid.return_value = None
    _run(mock_identity_cls, False)

    mock_identity_cls.return_value.is_entitled.assert_called_once_with("uid-1", "g1")
    mock_llm_cls.return_value.extract.assert_not_called()
    mock_folio_service.create.assert_not_called()
    mock_folio_service.update.assert_not_called()
    mock_session_repo.delete_session.assert_called_once_with("+5217779313704")
    sent = mock_whatsapp_cls.return_value.send_text_message.call_args[0][1]
    assert sent == NO_ACCESS_MESSAGE


@patch("app.services.WhatsappIntakeProcessorService.session_repo")
@patch("app.services.WhatsappIntakeProcessorService.folio_service")
@patch("app.services.WhatsappIntakeProcessorService.inbound_repo")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappService")
@patch("app.services.WhatsappIntakeProcessorService.LlmExtractionService")
@patch("app.services.WhatsappIntakeProcessorService.WhatsappSellerIdentityService")
def test_flush_with_entitlement_proceeds(
    mock_identity_cls,
    mock_llm_cls,
    mock_whatsapp_cls,
    mock_inbound_repo,
    mock_folio_service,
    mock_session_repo,
):
    mock_inbound_repo.find_by_message_sid.return_value = None
    mock_llm_cls.return_value.extract.side_effect = RuntimeError("model reached")
    try:
        _run(mock_identity_cls, True)
    except Exception:
        pass
    mock_llm_cls.return_value.extract.assert_called()
    sent = [c[0][1] for c in mock_whatsapp_cls.return_value.send_text_message.call_args_list]
    assert NO_ACCESS_MESSAGE not in sent
