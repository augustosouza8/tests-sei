import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sei_client import PDFDownloadOptions, PDFDownloadResult, Processo
from sei_client.config import load_settings
from sei_client.pdf import baixar_pdfs_em_lote, gerar_pdf_processo


def _build_processo(numero: str) -> Processo:
    return Processo(
        numero_processo=numero,
        id_procedimento=numero.replace(".", "").replace("/", ""),
        url=f"https://sei/processo/{numero}",
        visualizado=False,
        categoria="Recebidos",
    )


class PDFDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()
        self.processos = [
            _build_processo("1500.01.0000001/2024-11"),
            _build_processo("1500.01.0000002/2024-22"),
            _build_processo("1500.01.0000003/2024-33"),
        ]

    @patch("sei_client.pdf.baixar_pdf_processo")
    def test_baixar_pdfs_em_lote_sequencial(self, mock_baixar: MagicMock) -> None:
        mock_baixar.side_effect = [
            PDFDownloadResult(self.processos[0], True, Path("p1.pdf")),
            PDFDownloadResult(self.processos[1], False, None, erro="Falha"),
            PDFDownloadResult(self.processos[2], True, Path("p3.pdf")),
        ]

        options = PDFDownloadOptions(
            habilitado=True,
            limite_processos=None,
            diretorio_saida=Path("."),
            paralelo=False,
            workers=2,
            tentativas=2,
        )

        resultados = baixar_pdfs_em_lote(MagicMock(), self.settings, self.processos, options)
        self.assertEqual(len(resultados), 3)
        self.assertEqual(sum(r.sucesso for r in resultados), 2)
        self.assertEqual(mock_baixar.call_count, 3)

    @patch("sei_client.pdf.baixar_pdf_processo")
    def test_baixar_pdfs_em_lote_paralelo(self, mock_baixar: MagicMock) -> None:
        mock_baixar.return_value = PDFDownloadResult(self.processos[0], True, Path("p.pdf"))

        options = PDFDownloadOptions(
            habilitado=True,
            limite_processos=2,
            diretorio_saida=Path("."),
            paralelo=True,
            workers=2,
            tentativas=1,
        )

        resultados = baixar_pdfs_em_lote(MagicMock(), self.settings, self.processos, options)
        self.assertEqual(len(resultados), 2)
        self.assertEqual(mock_baixar.call_count, 2)

    @patch("sei_client.pdf.baixar_pdf_processo")
    def test_gerar_pdf_processo_reutiliza_rotina(self, mock_baixar: MagicMock) -> None:
        resultado_esperado = PDFDownloadResult(self.processos[0], True, Path("p1.pdf"))
        mock_baixar.return_value = resultado_esperado

        sessao = MagicMock()
        resultado = gerar_pdf_processo(sessao, self.settings, self.processos[0])
        self.assertIs(resultado, resultado_esperado)
        mock_baixar.assert_called_once()
        args, kwargs = mock_baixar.call_args
        self.assertIs(args[0], sessao)
        self.assertIs(args[1], self.settings)
        self.assertIs(args[2], self.processos[0])
        self.assertEqual(kwargs.get("tentativas", args[3] if len(args) > 3 else None), 1)


if __name__ == "__main__":
    unittest.main()

