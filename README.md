# FINOVA · Finanzas personales

Aplicación sencilla para registrar ingresos, gastos, préstamos, abonos y metas de ahorro. Usa Python estándar y SQLite; no requiere instalar paquetes externos.

## Ejecutar localmente

1. Instala Python 3.10 o posterior.
2. Abre una terminal en esta carpeta.
3. Ejecuta `python server.py`.
4. Visita [http://localhost:8001](http://localhost:8001).

La primera ejecución crea `claro.sqlite3` junto a `server.py`. La base mantiene los datos de forma local y no se incluye en Git.

## Datos y seguridad

- Cada cuenta tiene sus propios movimientos, préstamos, metas y aportes.
- Las contraseñas se guardan con PBKDF2-HMAC-SHA256 y una sal aleatoria.
- La sesión usa una cookie `HttpOnly` y `SameSite=Strict`.
- Las sesiones viven en memoria del servidor; al reiniciarlo habrá que iniciar sesión de nuevo.
- El servidor está configurado para escuchar únicamente en `127.0.0.1`. Esta configuración es para uso local y no debe exponerse directamente a Internet. Para desplegarlo públicamente hace falta HTTPS, sesiones persistentes, configuración de producción y copias de seguridad.

## Archivos principales

- `index.html`: estructura de la aplicación.
- `styles.css`: estilos adaptables.
- `app.js`: interfaz y comunicación con la API.
- `server.py`: API HTTP y almacenamiento SQLite.
- `finova-mark.svg`: símbolo vectorial de FINOVA usado como marca y favicon.
- `claro.sqlite3`: base de datos local, creada al iniciar el servidor e ignorada por Git.
