"""Tests for ClobClientWrapper (Story 1.5)."""

import logging
import unittest
from unittest.mock import MagicMock, patch

from btts_bot.clients.clob import ClobClientWrapper


class TestClobClientWrapperMissingEnvVars(unittest.TestCase):
    """AC #2: Missing env vars cause SystemExit with a non-zero code."""

    def test_missing_private_key_raises_system_exit(self, monkeypatch=None) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
        ):
            with self.assertRaises(SystemExit) as ctx:
                ClobClientWrapper()
        self.assertNotEqual(ctx.exception.code, 0)

    def test_missing_proxy_address_raises_system_exit(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"POLYMARKET_PRIVATE_KEY": "0xdeadbeef"},
                clear=True,
            ),
        ):
            with self.assertRaises(SystemExit) as ctx:
                ClobClientWrapper()
        self.assertNotEqual(ctx.exception.code, 0)

    def test_missing_private_key_error_message_does_not_expose_value(
        self,
    ) -> None:
        """Error message must not include any credential value (there is none)."""
        import io

        buf = io.StringIO()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("sys.stderr", buf),
        ):
            with self.assertRaises(SystemExit):
                ClobClientWrapper()

        output = buf.getvalue()
        self.assertIn("POLYMARKET_PRIVATE_KEY", output)
        # No credential value leaked (value is absent, so nothing to leak)
        # The message should NOT contain any 0x... style secret
        self.assertNotIn("0x", output)


@patch("btts_bot.clients.clob.ClobClient")
class TestClobClientWrapperInit(unittest.TestCase):
    """AC #1: Successful L1 → creds → L2 construction."""

    def _make_mocks(self, mock_clob_cls):
        """Helper: configure two sequential ClobClient instantiations."""
        mock_l1 = MagicMock()
        mock_creds = MagicMock()
        mock_creds.api_key = "test_key"
        mock_creds.api_secret = "test_secret"
        mock_creds.api_passphrase = "test_pass"
        mock_l1.create_or_derive_api_creds.return_value = mock_creds
        mock_l2 = MagicMock()
        mock_clob_cls.side_effect = [mock_l1, mock_l2]
        return mock_l1, mock_creds, mock_l2

    def test_init_success_stores_l2_client(self, mock_clob_cls) -> None:
        mock_l1, mock_creds, mock_l2 = self._make_mocks(mock_clob_cls)
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            wrapper = ClobClientWrapper()

        self.assertIs(wrapper._client, mock_l2)

    def test_init_calls_create_or_derive_api_creds(self, mock_clob_cls) -> None:
        mock_l1, mock_creds, mock_l2 = self._make_mocks(mock_clob_cls)
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            ClobClientWrapper()

        mock_l1.create_or_derive_api_creds.assert_called_once()

    def test_init_l2_constructed_with_signature_type_2_and_funder(self, mock_clob_cls) -> None:
        mock_l1, mock_creds, mock_l2 = self._make_mocks(mock_clob_cls)
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            ClobClientWrapper()

        l2_call = mock_clob_cls.call_args_list[1]
        self.assertEqual(l2_call.kwargs["signature_type"], 2)
        self.assertEqual(l2_call.kwargs["funder"], "0xproxy")

    def test_init_l2_constructed_with_derived_creds(self, mock_clob_cls) -> None:
        mock_l1, mock_creds, mock_l2 = self._make_mocks(mock_clob_cls)
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            ClobClientWrapper()

        l2_call = mock_clob_cls.call_args_list[1]
        self.assertIs(l2_call.kwargs["creds"], mock_creds)


@patch("btts_bot.clients.clob.ClobClient")
class TestClobClientWrapperDelegation(unittest.TestCase):
    """AC #4: method delegation to internal _client."""

    def _make_wrapper(self, mock_clob_cls):
        mock_l1 = MagicMock()
        mock_creds = MagicMock()
        mock_l1.create_or_derive_api_creds.return_value = mock_creds
        mock_l2 = MagicMock()
        mock_clob_cls.side_effect = [mock_l1, mock_l2]
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            wrapper = ClobClientWrapper()
        return wrapper, mock_l2

    def test_get_tick_size_delegates_to_internal_client(self, mock_clob_cls) -> None:
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_l2.get_tick_size.return_value = "0.01"

        result = wrapper.get_tick_size("token123")

        mock_l2.get_tick_size.assert_called_once_with("token123")
        self.assertEqual(result, "0.01")

    def test_get_order_book_delegates_to_internal_client(self, mock_clob_cls) -> None:
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        sentinel = object()
        mock_l2.get_order_book.return_value = sentinel

        result = wrapper.get_order_book("token123")

        mock_l2.get_order_book.assert_called_once_with("token123")
        self.assertIs(result, sentinel)

    def test_get_order_delegates_to_internal_client(self, mock_clob_cls) -> None:
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        sentinel = object()
        mock_l2.get_order.return_value = sentinel

        result = wrapper.get_order("order-id-abc")

        mock_l2.get_order.assert_called_once_with("order-id-abc")
        self.assertIs(result, sentinel)

    def test_post_order_delegates_to_internal_client(self, mock_clob_cls) -> None:
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        order_obj = MagicMock()
        sentinel = object()
        mock_l2.post_order.return_value = sentinel

        result = wrapper.post_order(order_obj, "GTC")

        mock_l2.post_order.assert_called_once_with(order_obj, "GTC")
        self.assertIs(result, sentinel)

    def test_cancel_order_calls_client_cancel_with_correct_dict(self, mock_clob_cls) -> None:
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_l2.cancel.return_value = {"success": True}

        result = wrapper.cancel_order("order-id-xyz")

        mock_l2.cancel.assert_called_once_with({"orderID": "order-id-xyz"})
        self.assertEqual(result, {"success": True})

    def test_cancel_orders_calls_client_cancel_orders_with_correct_list(
        self, mock_clob_cls
    ) -> None:
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_l2.cancel_orders.return_value = {"cancelled": 2}

        result = wrapper.cancel_orders(["id1", "id2"])

        mock_l2.cancel_orders.assert_called_once_with([{"orderID": "id1"}, {"orderID": "id2"}])
        self.assertEqual(result, {"cancelled": 2})


@patch("btts_bot.clients.clob.ClobClient")
class TestClobClientWrapperRetry(unittest.TestCase):
    """AC #1 / architecture: @with_retry on external-call methods."""

    def _make_wrapper(self, mock_clob_cls):
        mock_l1 = MagicMock()
        mock_creds = MagicMock()
        mock_l1.create_or_derive_api_creds.return_value = mock_creds
        mock_l2 = MagicMock()
        mock_clob_cls.side_effect = [mock_l1, mock_l2]
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            wrapper = ClobClientWrapper()
        return wrapper, mock_l2

    def test_get_order_book_returns_none_after_exhausting_retries(self, mock_clob_cls) -> None:
        """@with_retry: when all retries exhausted, wrapper returns None."""
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_l2.get_order_book.side_effect = Exception("network error")

        with patch("time.sleep"):  # speed up retries
            result = wrapper.get_order_book("token123")

        self.assertIsNone(result)
        self.assertEqual(mock_l2.get_order_book.call_count, 5)  # MAX_RETRIES = 5


@patch("btts_bot.clients.clob.ClobClient")
class TestClobClientWrapperCredentialLogging(unittest.TestCase):
    """AC #3: No credential values appear in logs."""

    def test_log_output_contains_no_credential_values(self, mock_clob_cls) -> None:
        private_key = "0xSECRETKEY99"
        proxy_address = "0xPROXYADDR88"

        mock_l1 = MagicMock()
        mock_creds = MagicMock()
        mock_creds.api_key = "MY_API_KEY"
        mock_creds.api_secret = "MY_API_SECRET"
        mock_creds.api_passphrase = "MY_PASSPHRASE"
        mock_l1.create_or_derive_api_creds.return_value = mock_creds
        mock_l2 = MagicMock()
        mock_clob_cls.side_effect = [mock_l1, mock_l2]

        with (
            patch.dict(
                "os.environ",
                {
                    "POLYMARKET_PRIVATE_KEY": private_key,
                    "POLYMARKET_PROXY_ADDRESS": proxy_address,
                },
            ),
            self.assertLogs("btts_bot.clients.clob", level=logging.DEBUG) as log_ctx,
        ):
            ClobClientWrapper()

        all_messages = "\n".join(log_ctx.output)
        self.assertNotIn(private_key, all_messages)
        self.assertNotIn(proxy_address, all_messages)
        self.assertNotIn(mock_creds.api_key, all_messages)
        self.assertNotIn(mock_creds.api_secret, all_messages)
        self.assertNotIn(mock_creds.api_passphrase, all_messages)


@patch("btts_bot.clients.clob.ClobClient")
class TestClobClientWrapperCreateBuyOrder(unittest.TestCase):
    """Tests for ClobClientWrapper.create_buy_order (Story 3.1)."""

    def _make_wrapper(self, mock_clob_cls):
        mock_l1 = MagicMock()
        mock_creds = MagicMock()
        mock_l1.create_or_derive_api_creds.return_value = mock_creds
        mock_l2 = MagicMock()
        mock_clob_cls.side_effect = [mock_l1, mock_l2]
        with patch.dict(
            "os.environ",
            {
                "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
                "POLYMARKET_PROXY_ADDRESS": "0xproxy",
            },
        ):
            wrapper = ClobClientWrapper()
        return wrapper, mock_l2

    def test_create_buy_order_constructs_correct_order_args(self, mock_clob_cls) -> None:
        """create_buy_order builds OrderArgs with correct token_id, price, size, side, expiration."""
        from py_clob_client.clob_types import OrderArgs

        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_signed = MagicMock()
        mock_l2.create_order.return_value = mock_signed
        mock_l2.post_order.return_value = {"orderID": "test-order"}

        with patch("btts_bot.clients.clob.OrderArgs", wraps=OrderArgs) as mock_order_args:
            wrapper.create_buy_order(
                token_id="token-abc",
                price=0.48,
                size=30.0,
                expiration_ts=9999999,
            )

        mock_order_args.assert_called_once()
        call_kwargs = mock_order_args.call_args.kwargs
        self.assertEqual(call_kwargs["token_id"], "token-abc")
        self.assertAlmostEqual(call_kwargs["price"], 0.48)
        self.assertAlmostEqual(call_kwargs["size"], 30.0)
        self.assertEqual(call_kwargs["side"], "BUY")
        self.assertEqual(call_kwargs["expiration"], 9999999)

    def test_create_buy_order_passes_gtd_order_type(self, mock_clob_cls) -> None:
        """create_buy_order calls post_order with OrderType.GTD."""
        from py_clob_client.clob_types import OrderType

        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_signed = MagicMock()
        mock_l2.create_order.return_value = mock_signed
        mock_l2.post_order.return_value = {"orderID": "gtd-order"}

        wrapper.create_buy_order(
            token_id="token-abc",
            price=0.48,
            size=30.0,
            expiration_ts=9999999,
        )

        mock_l2.post_order.assert_called_once_with(mock_signed, orderType=OrderType.GTD)

    def test_create_buy_order_returns_api_response(self, mock_clob_cls) -> None:
        """create_buy_order returns the response dict from post_order."""
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_signed = MagicMock()
        mock_l2.create_order.return_value = mock_signed
        expected_response = {"orderID": "resp-order-123", "status": "placed"}
        mock_l2.post_order.return_value = expected_response

        result = wrapper.create_buy_order(
            token_id="token-abc",
            price=0.48,
            size=30.0,
            expiration_ts=9999999,
        )

        self.assertIs(result, expected_response)

    def test_create_buy_order_returns_none_when_retry_exhausted(self, mock_clob_cls) -> None:
        """create_buy_order returns None when all retries are exhausted."""
        wrapper, mock_l2 = self._make_wrapper(mock_clob_cls)
        mock_l2.create_order.side_effect = Exception("network error")

        with patch("time.sleep"):
            result = wrapper.create_buy_order(
                token_id="token-abc",
                price=0.48,
                size=30.0,
                expiration_ts=9999999,
            )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
