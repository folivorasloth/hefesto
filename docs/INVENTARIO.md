# Inventário de componentes

O seu inventário fica em `data/usuario/inventario.yaml`, criado na primeira
vez a partir de `modelos/inventario.yaml` (que já traz o que você me passou).
É a lista única do que existe fisicamente na bancada. Ela
serve ao Hefesto (telemetria do Gol) e ao Divine Machinery. Toda
especificação diz de onde veio (`confirmado`, `provavel` ou `a_confirmar`,
com a `fonte`).

```bash
engenheiro inventario
```

```bash
engenheiro inventario --pendencias
```

```bash
engenheiro inventario --validar
```

O primeiro mostra a lista. O segundo mostra só o que falta confirmar, contar
ou fotografar. O terceiro confere o arquivo depois de editar à mão.

## Chegou peça nova

Copie um bloco de item no `data/usuario/inventario.yaml` e preencha. Só marque
`confirmado` o que você viu na peça ou mediu, e diga onde (`fonte`). O que
veio do anúncio é `provavel`. Rode `engenheiro inventario --validar`.

## Confirmando o ESP32 com o esptool

A foto mostra uma placa DevKit de 38 pinos com módulo estilo WROOM. O chip
"ESP32 clássico" é dedução da pinagem. Para confirmar:

1. Instale o esptool:

   ```bash
   pip install esptool
   ```

2. Ligue a placa no USB, com um cabo de **dados** (cabo só de carga não
   funciona), e veja qual porta apareceu. O conversor da placa é um CH9102X;
   no Linux ele costuma aparecer como `/dev/ttyACM0` ou `/dev/ttyUSB0`:

   ```bash
   ls /dev/ttyUSB* /dev/ttyACM*
   ```

   Se der erro de permissão ao abrir a porta, ponha seu usuário no grupo
   `dialout` e faça logout e login:

   ```bash
   sudo usermod -aG dialout $USER
   ```

3. Leia chip e flash, trocando a porta pela que apareceu no passo 2:

   ```bash
   esptool --port /dev/ttyACM0 flash-id
   ```

   Em versões antigas do esptool, o comando é
   `esptool.py --port /dev/ttyACM0 flash_id`.

4. Copie para o `data/usuario/inventario.yaml` (item `esp32-devkit-38p`) as linhas
   `Chip is ...` (ou `Chip type: ...`), `Features: ...` e `Detected flash
   size: ...`, e mude o status de `chip` para `confirmado` com
   `fonte: esptool <data>`.

O esptool não detecta PSRAM externa (a de um módulo WROVER). Para saber se
há PSRAM, rode um sketch que imprima `ESP.getPsramSize()` na IDE do Arduino.
Se der 0, não há.
