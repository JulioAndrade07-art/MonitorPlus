# 📁 Monitoramento de Pasta (MonitorPlus)

**[🇧🇷 Português](#-português-br) | [🇺🇸 English](#-english)**

---

# 🇧🇷 Português (BR)

Aplicativo desktop para Windows desenvolvido em **Python + PySide6 + Watchdog + SQLite** que monitora continuamente em segundo plano **qualquer pasta local ou compartilhamento de rede (`\\servidor\pasta`) escolhido pelo usuário**, detecta alterações em arquivos e subpastas em tempo real, envia notificações discretas na área de trabalho e disponibiliza uma **Central de Pendências (Checklist)** persistente para controlar todas as modificações verificadas ou resolvidas.

## ✨ Principais Funcionalidades

- **Seleção Livre do Diretório no Próprio Aplicativo**:
  - Digite ou escolha diretamente na tela principal qualquer diretório local (ex.: `C:\Projetos\Documentos`) ou pasta compartilhada na rede (ex.: `\\SERVIDOR\Compartilhamento\Arquivos`).
- **Monitoramento Recursivo Híbrido (Tempo Real + Varredura de Segurança)**:
  - **Camada 1 (`WatchdogMonitor`)**: Detecta eventos instantaneamente via API nativa do sistema operacional (`ReadDirectoryChangesW`), cobrindo a pasta principal e todas as subpastas existentes ou criadas futuramente.
  - **Camada 2 (`NetworkScanner`)**: Varredura periódica inteligente via `os.scandir` comparando metadados e hashes SHA-256 contra o snapshot local no SQLite, garantindo que nenhuma alteração seja perdida em pastas de rede.
  - **Reconexão Automática**: Detecta quedas de conexão em pastas de rede, registra no histórico, alerta o usuário e retoma o monitoramento automaticamente quando o diretório volta a ficar disponível.
- **8 Tipos de Eventos Detectados**:
  - `Novo arquivo`, `Arquivo modificado`, `Arquivo excluído`, `Arquivo renomeado`
  - `Nova pasta`, `Pasta modificada`, `Pasta excluída`, `Pasta renomeada`
- **Debounce Inteligente e Filtro de Arquivos Temporários**:
  - Consolida múltiplos salvamentos rápidos de um mesmo documento (ex.: 5 gravações em 2 segundos) em uma única notificação e pendência.
  - Ignora automaticamente arquivos temporários de editores e do sistema (`~$*.xlsx`, `~$*.docx`, `~WRL*.tmp`, `*.tmp`, `thumbs.db`, `desktop.ini`).
  - Diferencia arquivos com o mesmo nome em subpastas distintas através do caminho relativo e completo.
- **Sistema de Checklist Persistente (Central de Pendências)**:
  - Marque cada alteração como **Concluída (`☑`)** registrando data e horário da verificação, ou desmarque (`☐`) para **Reabrir a pendência**.
  - Adicione observações em cada item e visualize detalhes completos (tamanho, hash SHA-256, caminho antigo em renomeações).
  - Filtros rápidos: **Todas**, **Pendentes**, **Concluídas**, **Hoje**, **Últimos 7 dias**, **Últimos 30 dias**, filtro por **Tipo de Evento**, **Pesquisa instantânea** e **Ordenação por data**.
  - Botão **📂 Local** para destacar o arquivo diretamente no Windows Explorer (`explorer.exe /select`) sem executar/abrir os documentos alterados.
- **Operação 100% Somente-Leitura (Read-Only)**:
  - O aplicativo jamais altera, bloqueia, move ou exclui os arquivos monitorados.

## 🗂 Estrutura do Projeto

```text
MonitorPlus/
├── README.md                              # Documentação bilíngue (PT-BR / EN)
├── LICENSE                                # Licença MIT
├── .gitignore                             # Arquivos ignorados pelo Git
├── requirements.txt                       # Dependências Python
├── main.py                                # Ponto de entrada na raiz
├── build_exe.bat                          # Script para gerar o executável Windows (.exe)
├── iniciar_monitor.bat                    # Atalho para iniciar o aplicativo
├── desinstalar.bat                        # Script para remover inicialização automática
└── monitoramento_de_pasta/
    ├── main.py                            # Inicialização, CLI e bandeja do sistema
    ├── config.py                          # Configurações globais e filtro de temporários
    ├── config.example.json                # Exemplo de arquivo de configuração
    ├── assets/
    │   └── icon_generator.py              # Gerador programático do ícone (.ico e .png)
    ├── database/
    │   ├── database.py                    # Persistência SQLite (WAL, filtros, snapshots)
    │   └── models.py                      # Modelos de dados (EventRecord, TaskItem, etc.)
    ├── monitor/
    │   ├── watchdog_monitor.py            # Monitoramento recursivo em tempo real
    │   ├── network_scanner.py             # Varredura híbrida e reconexão automática
    │   ├── event_processor.py             # Debounce, agrupamento e deduplicação
    │   └── file_fingerprint.py            # Metadados read-only e hash SHA-256
    ├── notifications/
    │   └── windows_notifications.py       # Notificações nativas do Windows
    ├── interface/
    │   ├── main_window.py                 # Interface principal e seletor de pasta
    │   ├── task_list.py                   # Tabela de checklist e janela de detalhes
    │   ├── settings_window.py             # Janela de configurações e testes
    │   └── system_tray.py                 # Ícone e menu na bandeja do sistema
    ├── startup/
    │   └── windows_startup.py             # Inicialização automática com o Windows (HKCU)
    └── tests/
        ├── test_mandatory_scenarios.py    # Testes automatizados dos 14 cenários
        └── test_ui_and_filters.py         # Testes da interface e filtros
```

## 🚀 Instalação e Como Usar

### Pré-requisitos (Execução via Python)
- Windows 10 ou Windows 11
- Python 3.12 ou superior

```bash
git clone https://github.com/JulioAndrade07-art/MonitorPlus.git
cd MonitorPlus
pip install -r requirements.txt
python main.py
```

### Escolhendo a Pasta para Monitorar
1. Ao abrir o aplicativo, utilize a barra **"Local monitorado"** no topo da janela principal.
2. Clique em **📂 Selecionar Pasta...** para escolher qualquer pasta local ou de rede, ou digite o caminho manualmente e clique em **✔ Monitorar Local**.
3. O aplicativo fará a indexação inicial (*baseline*) silenciosamente e passará a monitorar e notificar todas as novas alterações em tempo real.
4. Ao fechar a janela no botão `X`, o aplicativo continua rodando em segundo plano no ícone próximo ao relógio do Windows (System Tray).

### Compilando o Executável `.exe` (Standalone)
Para gerar o executável único (`MonitoramentoDePasta.exe`) que funciona sem exigir Python instalado:

```cmd
build_exe.bat
```

O executável será gerado em `%LOCALAPPDATA%\MonitoramentoDePasta\dist\MonitoramentoDePasta.exe`.

### Executando os Testes Automatizados
```bash
pytest monitoramento_de_pasta/tests -v
```

---

# 🇺🇸 English

A lightweight, reliable Windows desktop application built with **Python + PySide6 + Watchdog + SQLite** that continuously monitors **any user-selected local folder or network share (`\\server\share`)** in the background, detects real-time file and subfolder changes, sends discrete Windows desktop notifications, and provides a persistent **Pending Changes Checklist** to track verified or resolved modifications.

## ✨ Key Features

- **User-Defined Folder Selection**:
  - Easily pick or type any local directory (e.g., `C:\Projects\Documents`) or network share (e.g., `\\SERVER\Shared\Folder`) directly from the main window header or Settings dialog.
- **Hybrid Recursive Monitoring (Real-Time Events + Safety Scanner)**:
  - **Layer 1 (`WatchdogMonitor`)**: Captures real-time filesystem events via the native Windows API (`ReadDirectoryChangesW`), recursively covering the root folder and all existing or newly created subfolders.
  - **Layer 2 (`NetworkScanner`)**: Periodic high-speed directory tree scan via `os.scandir`, comparing file metadata and SHA-256 hashes against a persisted SQLite snapshot so no events are ever missed on network shares.
  - **Automatic Reconnection**: Detects network disconnections, logs connection events, notifies the user, and automatically resumes monitoring and reconciles offline changes when the folder becomes available again.
- **8 Detected Event Types**:
  - `New file`, `Modified file`, `Deleted file`, `Renamed file`
  - `New folder`, `Modified folder`, `Deleted folder`, `Renamed folder`
- **Smart Debouncing & Temporary File Filtering**:
  - Consolidates rapid consecutive saves (e.g., 5 writes within 2 seconds) into a single notification and checklist item.
  - Automatically ignores temporary lock and swap files from Office and Windows (`~$*.xlsx`, `~$*.docx`, `~WRL*.tmp`, `*.tmp`, `thumbs.db`, `desktop.ini`).
  - Distinguishes files with identical names across different subfolders using full and relative paths.
- **Persistent Checklist System**:
  - Check off items as **Completed (`☑`)** with automatic completion timestamps, or uncheck (`☐`) to **Reopen** pending items.
  - Add custom notes/observations to any task and inspect full metadata (file size, SHA-256 hash, previous path on rename).
  - Rich filtering: **All**, **Pending**, **Completed**, **Today**, **Last 7 days**, **Last 30 days**, **Event Type**, **Instant Search**, and **Date Sorting**.
  - **📂 Location** button highlights the file directly in Windows Explorer (`explorer.exe /select`) without executing or opening the modified document.
- **Strictly Read-Only Operation**:
  - The monitor never modifies, locks, renames, or deletes any monitored files.

## 🚀 Getting Started

### Prerequisites (Running from Source)
- Windows 10 or Windows 11
- Python 3.12+

```bash
git clone https://github.com/JulioAndrade07-art/MonitorPlus.git
cd MonitorPlus
pip install -r requirements.txt
python main.py
```

### Selecting a Folder to Monitor
1. Open the application and locate the **"Local monitorado" (Monitored Location)** bar at the top of the main window.
2. Click **📂 Selecionar Pasta...** to browse for any local or network folder, or type/paste the path and click **✔ Monitorar Local**.
3. The app will silently index the initial baseline of existing files and immediately begin tracking and notifying new changes in real time.
4. Closing the main window (`X`) minimizes the app to the Windows System Tray so monitoring continues uninterrupted in the background.

### Building the Standalone Windows `.exe`
To compile a standalone single-file executable (`MonitoramentoDePasta.exe`) using PyInstaller:

```cmd
build_exe.bat
```

The executable is output to `%LOCALAPPDATA%\MonitoramentoDePasta\dist\MonitoramentoDePasta.exe`.

### Automatic Startup with Windows
- Enabled by default for the current user via `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run\MonitoramentoDePasta` (no administrator privileges required).
- Can be toggled at any time in **⚙ Configurações (Settings)**.
- To remove the startup registry entry and stop background processes, run `desinstalar.bat`.

### Running Automated Tests
```bash
pytest monitoramento_de_pasta/tests -v
```

---

## 📄 License / Licença

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
