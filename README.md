# Video Editor Pro

Aplicativo local de edição de vídeo automatizada com interface web (Gradio).

## Funcionalidades

| Funcionalidade | Descrição |
|---|---|
| **Melhoria de Áudio** | Redução de ruído, normalização de volume, compressão e EQ de voz |
| **Legendas de Impacto** | Transcrição com Whisper, legendas curtas estilo Reels, exportação .SRT |
| **Animações Visuais** | Detecção de pausas, títulos animados, slide-in com FFmpeg drawtext |

---

## Pré-requisitos

### FFmpeg (obrigatório)

**Windows**
1. Baixe em https://ffmpeg.org/download.html (escolha "Windows builds from gyan.dev")
2. Extraia o arquivo ZIP para `C:\ffmpeg`
3. Adicione `C:\ffmpeg\bin` à variável de ambiente `PATH`
4. Abra um novo terminal e verifique: `ffmpeg -version`

**macOS**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian)**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Linux (Fedora/RHEL)**
```bash
sudo dnf install ffmpeg
```

---

## Instalação

### 1. Clone ou baixe o projeto

```bash
git clone <url-do-repositorio>
cd video-editor-pro
```

### 2. Crie um ambiente virtual (recomendado)

**Windows**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

> **Nota sobre PyTorch / GPU:** O Whisper funciona na CPU, mas é significativamente mais rápido com GPU NVIDIA.
> Para instalar com suporte CUDA:
> ```bash
> pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
> ```

---

## Executando o app

```bash
python app.py
```

O navegador abrirá automaticamente em `http://127.0.0.1:7860`.

---

## Como usar

1. **Upload de vídeo** — arraste e solte ou clique para selecionar (MP4, MOV, AVI)
2. **Selecione as funcionalidades** desejadas com os checkboxes
3. **Configurações avançadas** (opcional):
   - Escolha o modelo Whisper (`tiny` = rápido, `large` = preciso)
   - Adicione um título customizado para o início do vídeo
4. Clique em **Processar Vídeo**
5. Aguarde o processamento (a barra de progresso mostra o andamento)
6. **Faça o download** do vídeo final e/ou do arquivo `.SRT`

---

## Modelos Whisper

| Modelo | Tamanho | Velocidade | Precisão |
|--------|---------|------------|---------|
| tiny   | ~39 MB  | ⚡⚡⚡⚡⚡ | ★★☆☆☆ |
| base   | ~74 MB  | ⚡⚡⚡⚡  | ★★★☆☆ |
| small  | ~244 MB | ⚡⚡⚡    | ★★★★☆ |
| medium | ~769 MB | ⚡⚡      | ★★★★★ |
| large  | ~1550 MB| ⚡        | ★★★★★ |

Na primeira execução o modelo escolhido é baixado automaticamente (~39–1550 MB).

---

## Processamento de Áudio (detalhes)

O pipeline de áudio usa os seguintes filtros FFmpeg em sequência:

1. **highpass=f=80** — corta frequências abaixo de 80 Hz (ruído de baixa frequência)
2. **lowpass=f=12000** — corta frequências acima de 12 kHz
3. **equalizer=f=3000:g=3** — realça presença de voz (2–5 kHz)
4. **compand** — compressão dinâmica para voz consistente
5. **loudnorm=I=-16** — normalização de loudness (padrão streaming)

---

## Estrutura do Projeto

```
video-editor-pro/
├── app.py           # aplicação principal
├── requirements.txt # dependências Python
└── README.md        # este arquivo
```

Arquivos temporários são criados em `<tmpdir>/vid_editor/` e podem ser removidos manualmente após o uso.

---

## Solução de Problemas

**"FFmpeg não encontrado"**
→ Instale o FFmpeg e certifique-se de que está no PATH (veja acima).

**"CUDA out of memory"**
→ Use um modelo Whisper menor (tiny ou base) ou processe em CPU.

**Legendas não aparecem**
→ Verifique se o vídeo tem áudio audível. Para áudio muito baixo, ative primeiro a "Melhoria de Áudio".

**Erro ao instalar `openai-whisper` no Windows**
→ Certifique-se de ter o Visual C++ Build Tools instalado: https://visualstudio.microsoft.com/visual-cpp-build-tools/

---

## Requisitos do Sistema

- Python 3.10+
- FFmpeg 4.x ou superior
- 4 GB de RAM (mínimo); 8 GB recomendado para modelos `medium`/`large`
- Espaço em disco: ~2 GB para dependências + modelos Whisper
