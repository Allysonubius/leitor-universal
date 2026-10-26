# Leitor Universal

Leitor de livros para desktop (Windows) que abre praticamente qualquer formato, organiza
uma biblioteca com capas e **lembra exatamente onde você parou**.

## Recursos

- **Biblioteca por pastas**: no primeiro uso, escolha a pasta onde ficam seus livros. Tudo o
  que estiver nela (e nas subpastas) vira a biblioteca, em qualquer formato. Arquivos novos
  aparecem sozinhos; arquivos apagados somem da estante sem perder o progresso (se voltarem,
  o progresso volta junto). Pastas em pen drives desconectados não são afetadas.
- **Configurações** (⚙): pastas da biblioteca, subpastas, monitoramento automático, formatos
  incluídos, tema, abrir o último livro ao iniciar e atualizações automáticas.
- **Abertura avulsa**: arraste um arquivo para a janela, use **⋮ → Abrir um arquivo avulso** ou
  “Abrir com”. Arrastar uma pasta a adiciona à biblioteca.
- **Retomada automática**: cada livro reabre na última página lida. Em livros refluíveis
  (EPUB, MOBI, TXT, DOCX…) a posição é salva por capítulo, então continua correta mesmo
  depois de mudar o tamanho da fonte ou da janela.
- **Marcadores com anotações** (Ctrl+D), **sumário** navegável e **busca** no texto com
  destaque dos resultados (Ctrl+F, F3 / Shift+F3).
- **Biblioteca** com capas, progresso, filtros (lendo, não iniciados, concluídos, favoritos),
  ordenação e botão **Continuar leitura**.
- **Seleção de texto e grifos**: arraste sobre o texto para copiar (Ctrl+C), grifar em quatro
  cores (Ctrl+H grifa em amarelo), anotar, ver a **definição** (Wikcionário) ou **traduzir**
  (MyMemory). Em EPUB/MOBI os grifos sobrevivem à mudança de fonte.
- **Anotações**: todos os grifos de todos os livros, com busca, filtros e exportação para Markdown.
- **Leitura em voz alta** com as vozes do Windows (🔊 Ouvir ou F5), virando as páginas sozinha.
- **Coleções** próprias e **séries** detectadas pelo título (“Duna 2”, “Livro 3”, “vol. 1”…).
- **Capa e dados da internet**: botão direito no livro → *Buscar capa e dados na internet*
  (Open Library).
- **Estatísticas**: minutos por dia, dias seguidos lendo, livros por mês, metas diária e anual
  e estimativa de tempo restante em cada livro.
- **Backup e sincronização**: backup/restauração em `.zip` e sincronização entre PCs por uma
  pasta do OneDrive, Google Drive ou Dropbox (progresso, marcadores, grifos e coleções).
- Temas **Claro, Sépia e Escuro**, **rolagem contínua**, modo **duas páginas**, zoom (largura,
  página inteira, livre, Ctrl + roda), ajuste de fonte, **tela cheia** (F11).
- **Uma janela só**: abrir um livro pelo Explorer com o app aberto usa a janela existente.
- Arquivos movidos ou renomeados são reconhecidos pela impressão digital do conteúdo, sem
  perder progresso.

## Formatos

| Tipo | Extensões | Como |
|---|---|---|
| Nativos | PDF, EPUB, MOBI, AZW/AZW3, PRC, FB2, XPS/OXPS, CBZ, SVG, HTML/XHTML, imagens | MuPDF |
| Convertidos | TXT (UTF-8/ANSI), Markdown, RTF, DOCX, CBR, ZIP de imagens | em memória |
| Office | DOC, ODT, PPT/PPTX, XLS/XLSX, ODP, ODS | requer [LibreOffice](https://www.libreoffice.org) |
| Outros | qualquer arquivo de texto (ex.: `.py`, `.log`) | aberto como texto |

> CBR em formato RAR real exige o WinRAR ou o 7-Zip instalado. Arquivos com DRM não são suportados.

## Instalação

Baixe o `LeitorUniversal-X.Y.Z-setup.exe` da
[última release](https://github.com/Allysonubius/leitor-universal/releases/latest) e execute.
A instalação é por usuário (não pede administrador), cria atalhos e adiciona o leitor ao menu
**Abrir com** dos formatos de livro. Há também uma versão portátil (`-portable.zip`).

### Atualizações obrigatórias

A cada abertura (e a cada 6 h com o app aberto) o aplicativo consulta as releases no GitHub. Se
houver versão nova, mostra **as novidades de todas as versões que faltam** e só oferece
**Atualizar agora**; fechar o aviso encerra o aplicativo. O instalador é baixado, tem o SHA-256
conferido com o `SHA256SUMS.txt` da release, é executado silenciosamente e reabre o app.
Biblioteca, progresso e marcadores são preservados. Sem internet, o app abre normalmente e tenta
de novo depois. Erros ficam registrados em `%APPDATA%\LeitorUniversal\leitor.log`.

## Desenvolvimento

Requer Python 3.10+ (testado com 3.12).

```bash
py -3.12 -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python.exe -m pip install pytest pyinstaller
```

Executar a partir do código-fonte:

```bash
.\LeitorUniversal.bat
```

Rodar os testes:

```bash
.venv\Scripts\python.exe -m pytest -q tests
```

### Fluxo de trabalho com o GitHub

1. Faça as alterações, depois `git add .`, `git commit -m "descrição"` e `git push`. O
   workflow **CI** roda os testes a cada push.
2. Descreva as novidades em `## [Não publicado]` no [CHANGELOG.md](CHANGELOG.md). Esse texto
   é o que os usuários veem no aviso de atualização (o script recusa publicar sem ele).
3. Rode o script abaixo. Ele testa, incrementa a versão, data a seção do CHANGELOG, cria a tag e
   envia. O workflow **Release** gera o instalador, a versão portátil e os checksums e publica a
   release com essas notas; os apps instalados são obrigados a atualizar.

```bash
.\scripts\publicar.ps1
```

Use `-Tipo minor` para novidades, `-Tipo major` para mudanças grandes ou `-Versao 2.0.0`.

Para gerar o instalador localmente (requer [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```bash
.venv\Scripts\pyinstaller.exe packaging\LeitorUniversal.spec --noconfirm
```

```bash
iscc /DAppVersion=1.0.0 packaging\installer.iss
```

## Uso

Também é possível passar arquivos: `LeitorUniversal.bat "C:\Livros\meu livro.epub"`.
Para abrir com duplo clique, use **Abrir com → Escolher outro aplicativo → LeitorUniversal.bat**
no Explorer.

### Atalhos

| Ação | Teclas |
|---|---|
| Próxima / anterior | → / ←, PgDn / PgUp, Espaço, clique nas laterais, roda do mouse no fim da página |
| Início / fim | Home / End |
| Zoom | Ctrl + roda, Ctrl+= / Ctrl+-, Ctrl+0 (página inteira) |
| Marcador | Ctrl+D |
| Selecionar texto | arrastar com o botão esquerdo; duplo clique seleciona uma palavra |
| Copiar / grifar seleção | Ctrl+C / Ctrl+H (outras cores e opções no botão direito) |
| Mover página ampliada | arrastar com o botão do meio |
| Ler em voz alta | F5 |
| Buscar | Ctrl+F, F3 / Shift+F3 |
| Painel lateral | Ctrl+B |
| Tela cheia | F11 (Esc sai) |

## Dados

Biblioteca, progresso, marcadores, grifos, coleções, estatísticas e preferências ficam em
`%APPDATA%\LeitorUniversal\biblioteca.db` (SQLite). Conversões do LibreOffice ficam em
`%APPDATA%\LeitorUniversal\cache`. Remover um livro da biblioteca **nunca** apaga o arquivo.

Dicionário, tradução e busca de capas só consultam a internet quando você pede, enviando
apenas a palavra, o trecho ou o título escolhido.

## Assinatura digital (aviso do SmartScreen)

Sem assinatura, o Windows mostra “O Windows protegeu o computador” ao abrir o instalador
baixado. O workflow de release já assina o executável e o instalador **quando o certificado
está configurado**; sem ele, a release sai normalmente, sem assinatura.

1. Obtenha um certificado de assinatura de código (`.pfx`), de uma autoridade certificadora
   (Sectigo, DigiCert, Certum etc.). Certificados EV removem o aviso imediatamente; os comuns
   ganham reputação com o tempo.
2. No GitHub, em **Settings → Secrets and variables → Actions**, crie:
   - `WINDOWS_CERT_PFX_BASE64`: o conteúdo do `.pfx` em Base64
     (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))` no PowerShell);
   - `WINDOWS_CERT_PASSWORD`: a senha do `.pfx`.
3. A próxima versão publicada já sai assinada ([scripts/assinar.ps1](scripts/assinar.ps1)).

## Estrutura

```
leitor_universal/
  app.py               janela principal, navegação lateral, importação, backup, sincronização
  documents.py         abertura universal, conversores de formato e detecção de séries
  library.py           persistência SQLite (livros, progresso, marcadores, grifos, coleções, estatísticas)
  library_view.py      estante de capas reutilizável e tela da Biblioteca
  collections_view.py  coleções e séries
  annotations_view.py  todos os grifos e exportação para Markdown
  stats_view.py        estatísticas, metas e gráficos
  reader.py            leitura: modos de página, seleção, grifos, voz, dicionário, busca
  speech.py            leitura em voz alta (vozes do Windows)
  online.py            dicionário, tradução e Open Library
  metadata_dialog.py   busca de capa e dados do livro
  sync.py              backup, restauração e sincronização entre PCs
  single_instance.py   uma janela só (repasse de arquivos)
  scanner.py           sincronização das pastas da biblioteca (em segundo plano)
  settings_dialog.py   tela de Configurações e preferências
  themes.py            temas da interface e coloração das páginas
  updater.py           verificação, download e instalação de atualizações
packaging/         especificação do PyInstaller, instalador Inno Setup e ícone
scripts/           publicar.ps1 (nova versão), assinar.ps1, notas_da_versao.py e gerar_icone.py
tests/             testes automatizados e gerador de arquivos de exemplo
.github/workflows/ CI (testes) e Release (instalador + publicação)
run.pyw            inicializador sem console
LeitorUniversal.bat
```
