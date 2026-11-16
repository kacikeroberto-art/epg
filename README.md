# EPG automático para tu lista IPTV

Genera cada lunes un XMLTV con solo los canales de tu lista, uniendo las guías
de Perú, Chile, Argentina, México, España, Colombia y Uruguay.

No contiene tu lista ni tus credenciales: solo los `tvg-id` de los canales
(`ids.txt`) y las URLs públicas de las guías (`epg-sources.txt`).

## Puesta en marcha (5 minutos, una sola vez)

### 1. Crea el repositorio

En GitHub: **New repository** → nombre `epg` → **Public** (obligatorio, si es
privado la URL no funciona sin token) → Create.

### 2. Sube estos archivos

En el repo: **Add file → Upload files** y arrastra todo el contenido de esta
carpeta, respetando la ruta:

```
epg-merge.py
ids.txt
epg-sources.txt
.github/workflows/epg.yml
```

Ojo con `.github/`: si tu explorador de archivos oculta las carpetas que
empiezan con punto, créala a mano con **Add file → Create new file** y escribe
la ruta completa `.github/workflows/epg.yml`, pegando el contenido.

Luego **Commit changes**.

### 3. Da permiso de escritura a Actions

**Settings → Actions → General → Workflow permissions** →
marca **Read and write permissions** → Save.

Sin esto, el job corre pero no puede guardar el archivo.

### 4. Pruébalo

**Actions → Actualizar EPG → Run workflow**. En un minuto tendrás `epg.xml` y
`epg.xml.gz` en el repo.

## Tu URL definitiva

```
https://raw.githubusercontent.com/TU_USUARIO/epg/main/epg.xml.gz
```

Esa URL **nunca cambia**. Pégala en el campo EPG/XMLTV del reproductor y olvídate:
cada lunes se regenera sola.

Si tu reproductor no acepta `.gz`, usa `.../main/epg.xml`.

## Mantenimiento

- **Cambiaste de lista o agregaste canales**: reemplaza `ids.txt` y haz commit.
- **Quieres más países**: agrega la línea de la guía en `epg-sources.txt`
  (formato `https://epgshare01.online/epgshare01/epg_ripper_XX1.xml.gz`).
- **Cambiar el día**: edita el `cron` en `.github/workflows/epg.yml`.
  Formato: minuto hora día-mes mes día-semana, en UTC. `0 6 * * 1` = lunes 06:00 UTC.
- **Correr a mano cuando quieras**: Actions → Actualizar EPG → Run workflow.

## Probar en tu PC antes de subirlo

```powershell
python epg-merge.py --ids-file ids.txt --epg (Get-Content epg-sources.txt) -join ',' --out epg.xml
```
