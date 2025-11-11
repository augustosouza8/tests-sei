import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List
from unittest.mock import MagicMock, patch

from sei_client import (
    Documento,
    Processo,
    PDFDownloadOptions,
    PDFDownloadResult,
    carregar_historico_processos,
    salvar_historico_processos,
)
from sei_client.config import load_settings
from sei_client.documents import parse_documentos_do_iframe
from sei_client.pdf import baixar_pdf_processo, baixar_pdfs_em_lote


SAMPLE_IFRAME_HTML = """
<html>
  <body>
    <script type="text/javascript">
      Nos[0] = new infraArvoreNo('DOCUMENTO','DOC-001','ROOT','/sei/controlador.php?acao=documento_visualizar&id_documento=DOC-001&infra_hash=hash001','ifrVisualizar','','Oficio de Teste (0001)','/sei/img/documento_pdf.svg','','','','','','','noVisitado','0001');
      Nos[1] = new infraArvoreNo('DOCUMENTO','DOC-002','ROOT','/sei/controlador.php?acao=documento_visualizar&id_documento=DOC-002&infra_hash=hash002','ifrVisualizar','','Anexo Plano (0002)','/sei/img/documento_pdf.svg','','','','','','','','0002');
      Nos[0].src = '/sei/controlador.php?acao=documento_download_anexo&id_anexo=ANX-001';
      Nos[0].html = "<a href='/sei/controlador.php?acao=documento_visualizar&id_documento=DOC-001'>Visualizar</a>";
      Nos[1].src = '/sei/controlador.php?acao=documento_download_anexo&id_anexo=ANX-002';
      NosAcoes[0] = new infraArvoreAcao('ASSINATURA','DOC-001',"alert('Assinado por\\nFulano de Tal')",null,null,null,null);
      NosAcoes[1] = new infraArvoreAcao('NIVEL_ACESSO','DOC-002',"alert('Acesso Restrito')",null,null,null,'/sei/img/sigilo.svg');
    </script>
  </body>
</html>
""".strip()


class DocumentParserTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()

    def test_parse_documentos_do_iframe(self) -> None:
        documentos = parse_documentos_do_iframe(self.settings, SAMPLE_IFRAME_HTML)

        self.assertEqual(len(documentos), 2)

        doc1 = documentos[0]
        self.assertEqual(doc1.id_documento, "DOC-001")
        self.assertEqual(doc1.titulo, "Oficio de Teste (0001)")
        self.assertTrue(doc1.eh_novo)
        self.assertEqual(doc1.metadados.get("icone_slug"), "documento_pdf.svg")
        self.assertIn("documento_visualizar", doc1.visualizacao_url or "")
        self.assertIn("documento_download_anexo", doc1.download_url or "")

        doc2 = documentos[1]
        self.assertEqual(doc2.id_documento, "DOC-002")
        self.assertTrue(doc2.eh_sigiloso)
        self.assertIn("Acesso Restrito", doc2.metadados.get("nivel_acesso", ""))

    def test_parse_documentos_com_assinaturas(self) -> None:
        processo = Processo(
            numero_processo="0001/2025",
            id_procedimento="PROC-001",
            url="https://example/processo",
            visualizado=False,
            categoria="Recebidos",
        )

        documentos = parse_documentos_do_iframe(self.settings, SAMPLE_IFRAME_HTML, processo=processo)
        doc = next((d for d in documentos if d.id_documento == "DOC-001"), None)
        self.assertIsNotNone(doc, "Documento DOC-001 não encontrado na árvore")
        assert doc is not None

        self.assertTrue(doc.possui_assinaturas)
        self.assertIn("Fulano de Tal", doc.assinantes)
        self.assertIn("Fulano de Tal", processo.assinantes)

    def test_salvar_e_carregar_historico(self) -> None:
        processo = Processo(
            numero_processo="0001/2025",
            id_procedimento="PROC-001",
            url="https://www.sei.example/sei/controlador.php?acao=procedimento_trabalhar&id_procedimento=PROC-001",
            visualizado=False,
            categoria="Recebidos",
        )
        processo.eh_sigiloso = True
        processo.assinantes = ["Fulano da Silva"]
        processo.metadados = {"nivel_acesso": "Acesso Restrito"}
        processo.documentos = [
            Documento(
                id_documento="DOC-001",
                titulo="Documento Sigiloso",
                tipo="DOCUMENTO",
                url="https://www.sei.example/sei/controlador.php?acao=arvore_visualizar&id_documento=DOC-001",
                download_url="https://www.sei.example/sei/controlador.php?acao=documento_download_anexo&id_anexo=ANX-001",
                indicadores=["noVisitado"],
                eh_novo=True,
                eh_sigiloso=True,
                possui_assinaturas=True,
                assinantes=["Fulano da Silva"],
                metadados={"nivel_acesso": "Acesso Restrito"},
            )
        ]

        with TemporaryDirectory() as tmpdir:
            historico_path = Path(tmpdir) / "historico.json"
            salvar_historico_processos(self.settings, [processo], historico_path)

            self.assertTrue(historico_path.exists())

            dados_raw = json.loads(historico_path.read_text(encoding="utf-8"))
            self.assertIn("PROC-001", dados_raw)

            dados = carregar_historico_processos(self.settings, historico_path)
            self.assertEqual(len(dados), 1)
            registro = dados["PROC-001"]
            self.assertEqual(registro["numero_processo"], processo.numero_processo)
            self.assertTrue(registro["eh_sigiloso"])
            self.assertIn("Fulano da Silva", registro["assinantes"])
            self.assertEqual(len(registro["documentos"]), 1)
            self.assertTrue(registro["documentos"][0]["eh_sigiloso"])


class PDFDownloadTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()
        self.processo = Processo(
            numero_processo="0001/2025",
            id_procedimento="PROC-001",
            url="https://example/processo",
            visualizado=False,
            categoria="Recebidos",
        )

    @patch("sei_client.pdf.enviar_form_gerar")
    @patch("sei_client.pdf.abrir_pagina_gerar_pdf")
    @patch("sei_client.pdf.achar_link_gerar_pdf", return_value="https://example/link_pdf")
    @patch("sei_client.documents.carregar_iframe_arvore", return_value="<html></html>")
    @patch("sei_client.documents.extrair_iframe_arvore_src", return_value="https://example/iframe")
    @patch("sei_client.processes.abrir_processo", return_value="<html></html>")
    def test_baixar_pdf_processo_sucesso(
        self,
        mock_abrir_processo,
        mock_iframe_src,
        mock_carregar_iframe,
        mock_link_pdf,
        mock_abrir_form,
        mock_enviar_form,
    ) -> None:
        mock_abrir_form.return_value = "<form></form>"
        destino_pdf = Path("/tmp/processo_0001_2025.pdf")
        mock_enviar_form.return_value = destino_pdf

        fake_session = MagicMock()
        resultado = baixar_pdf_processo(fake_session, self.settings, self.processo, tentativas=1)

        self.assertTrue(resultado.sucesso)
        self.assertEqual(resultado.caminho, destino_pdf)
        mock_enviar_form.assert_called_once()

    @patch("sei_client.pdf.baixar_pdf_processo")
    @patch("sei_client.pdf.time.sleep", return_value=None)
    def test_baixar_pdfs_em_lote_sequencial(self, mock_sleep, mock_baixar_pdf_processo) -> None:
        processos = [
            Processo(
                numero_processo=f"PROC-{i}",
                id_procedimento=str(1000 + i),
                url="https://example",
                visualizado=False,
                categoria="Recebidos",
            )
            for i in range(3)
        ]

        def _fake_baixar(session, settings, processo, tentativas=3, diretorio_saida=None):
            caminho = Path(diretorio_saida or ".") / f"{processo.id_procedimento}.pdf"
            return PDFDownloadResult(
                processo=processo,
                sucesso=True,
                caminho=caminho,
                erro=None,
                tentativas=1,
                tempo_segundos=0.1,
            )

        mock_baixar_pdf_processo.side_effect = _fake_baixar

        with TemporaryDirectory() as tmpdir:
            options = PDFDownloadOptions(
                habilitado=True,
                limite_processos=None,
                diretorio_saida=Path(tmpdir),
                paralelo=False,
                workers=2,
                tentativas=1,
            )

            fake_session = MagicMock()
            resultados = baixar_pdfs_em_lote(fake_session, self.settings, processos, options)

            self.assertEqual(len(resultados), 3)
            self.assertTrue(all(r.sucesso for r in resultados))
            mock_baixar_pdf_processo.assert_called()


if __name__ == "__main__":
    unittest.main()

