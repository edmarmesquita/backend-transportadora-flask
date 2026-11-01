import unittest
from datetime import datetime, timedelta, timezone

from utils.datas import (
    formatar_data_brasilia,
    formatar_instante_utc_brasilia,
    instante_atual_utc,
    serializar_instante_utc,
)


class DatasTest(unittest.TestCase):
    def test_instante_atual_e_aware_em_utc(self):
        atual = instante_atual_utc()

        self.assertIsNotNone(atual.tzinfo)
        self.assertEqual(atual.utcoffset(), timedelta(0))

    def test_utc_aware_serializa_com_z_explicito(self):
        valor = datetime(2026, 11, 1, 10, 10, 29, tzinfo=timezone.utc)

        self.assertEqual(serializar_instante_utc(valor), "2026-11-01T10:10:29Z")

    def test_utc_naive_legado_e_interpretado_como_utc(self):
        valor = datetime(2026, 11, 1, 10, 10, 29)

        self.assertEqual(serializar_instante_utc(valor), "2026-11-01T10:10:29Z")

    def test_offset_nao_utc_e_normalizado_para_utc(self):
        valor = datetime.fromisoformat("2026-11-01T12:10:29+02:00")

        self.assertEqual(serializar_instante_utc(valor), "2026-11-01T10:10:29Z")

    def test_microssegundos_sao_preservados(self):
        valor = datetime(2026, 11, 1, 10, 10, 29, 123456, tzinfo=timezone.utc)

        self.assertEqual(
            serializar_instante_utc(valor),
            "2026-11-01T10:10:29.123456Z",
        )

    def test_none_em_campos_opcionais(self):
        self.assertIsNone(serializar_instante_utc(None))
        self.assertEqual(formatar_instante_utc_brasilia(None), "")

    def test_utc_converte_para_sao_paulo(self):
        valor = datetime(2026, 10, 31, 11, 56, tzinfo=timezone.utc)

        self.assertEqual(formatar_instante_utc_brasilia(valor), "31/10/2026 08:56")

    def test_virada_de_dia_preserva_data_local_anterior(self):
        valor = datetime(2026, 11, 1, 1, 30, tzinfo=timezone.utc)

        self.assertEqual(formatar_instante_utc_brasilia(valor), "31/10/2026 22:30")

    def test_virada_de_mes_preserva_mes_local_anterior(self):
        valor = datetime(2026, 11, 1, 2, 30, tzinfo=timezone.utc)

        self.assertEqual(formatar_instante_utc_brasilia(valor), "31/10/2026 23:30")

    def test_formatador_legado_preserva_comportamento_com_naive_utc(self):
        valor = datetime(2026, 10, 31, 11, 56)

        self.assertEqual(formatar_data_brasilia(valor), "31/10/2026 08:56")
        self.assertEqual(formatar_data_brasilia(None), "")


if __name__ == "__main__":
    unittest.main()
