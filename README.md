# prometheus-exporter


## Esquema de funcionamiento
```
+------------------+                   +--------------------+
|    Script/App    |                   |  Prometheus Server |
|  (Mide sistemas) |                   | (TSDB / Engine)    |
+--------+---------+                   +---------+----------+
|                                                |
| 1. Actualiza métricas en RAM                   |
v                                                |
+-------+--------+                               |
| Prometheus     |                               |
| Client Library |                               |
+-------+--------+                               |
|                                                |
| 2. Expone servidor web                         |
v                                                |
+-------+--------+      3. HTTP GET /metrics     |
|  HTTP Server   | <-----------------------------+
|  (Puerto 9150) |                               |
+-------+--------+      4. Texto plano (Métricas)|
| ------------------------------------> |
|                                       | 5. Almacena con Timestamp
|                                       v
+                               +-------+--------+
                                |  TSDB (Disco)  |
                                +----------------+
```


## Anatomía de una Métrica en Formato Texto
Cuando Prometheus realiza el scrape, el exportador vuelca los datos de la memoria RAM al cuerpo de la respuesta HTTP utilizando la siguiente estructura:

```
# HELP sre_solicitudes_procesadas_total Cantidad total de solicitudes procesadas por el componente
# TYPE sre_solicitudes_procesadas_total counter
sre_solicitudes_procesadas_total{componente="auth-service",estado="200"} 4521.0
sre_solicitudes_procesadas_total{componente="auth-service",estado="500"} 12.0
```

- HELP: Una descripción clara de qué mide la métrica.
- TYPE: Informa a Prometheus qué tipo de estructura matemática tiene (counter, gauge, etc.) para que sepa qué funciones de PromQL permitir.
- Labels/Etiquetas ({key="value"}): Proveen la dimensionalidad de los datos. En lugar de crear una métrica distinta para cada combinación de error o servicio, se usa la misma métrica base discriminada por etiquetas. Esto permite realizar agregaciones dinámicas en Grafana (ej: sumar todos los errores sin importar el componente).

# 2. ¿Qué ofrece este Script/Plantilla?
Este script fue diseñado como una caja de herramientas pedagógica y de producción. Implementa el 100% de las capacidades de instrumentación que ofrece la librería oficial prometheus_client de Python, sirviendo como catálogo de referencia de:

## Los 4 Tipos de Métricas Core de Prometheus
- Counter (Contador Monotónico): Un valor que solo incrementa (.inc()). Se utiliza para registrar volúmenes totales (peticiones entrantes, bytes transferidos, errores gatillados). En Grafana nunca se grafica el Counter directamente; se envuelve en funciones de tasa como rate() o increase() para obtener eventos por segundo.

- Gauge (Indicador Instantáneo): Un valor que puede subir o bajar arbitrariamente (.set(), .inc(), .dec()). Es ideal para representar niveles actuales como uso de memoria RAM, temperatura, concurrencia en colas o tiempos del último chequeo sintético (latencia instantánea).
- Histogram (Distribución en Buckets): Mide la duración o tamaño de eventos y los distribuye automáticamente en rangos configurables (buckets). Genera series temporales como _bucket, _sum y _count. Es el estándar de SRE para calcular percentiles agregados (p95, p99) de múltiples servidores concurrentes usando la función histogram_quantile() de PromQL.
- Summary (Percentiles del Lado del Cliente): Mide duraciones al igual que el Histograma, pero calcula los quantiles exactos (ej: la mediana o el percentil 99) dentro del propio proceso de Python. Consume más CPU en el exportador pero provee percentiles exactos sin penalizar al servidor Prometheus con cálculos pesados. Nota arquitectónica: No se pueden promediar matemáticamente entre múltiples réplicas de exportadores en Grafana.

## Patrones Avanzados Incluidos
- Métricas de Metadatos (Info y Enum): Permite exponer datos estáticos que no cambian (versión del software, entorno de despliegue) y máquinas de estados lógicos estructurados en texto plano (ej: ONLINE, DEGRADED, MAINTENANCE).

- Instrumentación Nativa de Tiempos (Context Managers): Uso de bloques with METRICA.time(): para medir tiempos de ejecución de forma nativa en Python sin necesidad de restar variables time.time() manuales.

- Aislamiento por Hilos (Multi-threading): Arquitectura desacoplada mediante threading.Thread en modo demonio (daemon=True) que asegura que las tareas de recolección de fondo no bloqueen la disponibilidad del servidor HTTP principal.

- Métricas de Sanidad del Exporter (Runtime Metrics): Configuración modificada del registro global (REGISTRY) para aislar y exponer métricas de performance del propio script de Python bajo el namespace personalizado sre_exporter_runtime (Uso de CPU del proceso, consumo de memoria RSS/VMS, cantidad de hilos internos y File Descriptors abiertos).

# 3. Guía de Adaptación: ¿Qué tenés que modificar para tu proyecto?
Para transformar esta plantilla en tu exportador definitivo de infraestructura o aplicación, debés adaptar los siguientes bloques de código:

## a. Configuración de Red y Puertos
En la sección final (if __name__ == '__main__':), definí el puerto TCP donde tu exportador escuchará las peticiones de Prometheus. Aseguráse de que este puerto esté libre en tus políticas de firewall o mapeos de contenedores (Podman/Docker).

```
PUERTO_EXPORTER = 9150 # <-- Reemplazar por el puerto asignado a tu arquitectura
```

## b. Definición y Nombres de Métricas
Modificá la declaración de variables globales en la cabecera. Es Mandatorio seguir las buenas prácticas de nomenclatura de Prometheus:

Utilizar nombres en minúsculas separados por guiones bajos (_).

Los contadores deben llevar el sufijo _total (ej: sre_solicitudes_procesadas_total).

Definí etiquetas descriptivas de baja cardinalidad (evitá meter IDs de usuarios únicos o hashes dinámicos como etiquetas, ya que saturarán la memoria de Prometheus).

```
MI_METRICA_NUEVA = Gauge(
    'infra_estado_componente_nivel',
    'Descripción clara de lo que mide esta métrica',
    ['datacenter', 'dispositivo_tipo'] # <-- Tus etiquetas personalizadas
)
```

## c. Ajuste de Rangos para SLAs (Buckets)
Si vas a utilizar el Histogram para medir latencias de red o de HTTP, adaptá la tupla de buckets en segundos. Los buckets deben representar los umbrales críticos de tus Acuerdos de Nivel de Servicio (SLA/SLO).
```
buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf"))
```

## d. Sustitución de Simuladores por Lógica Real
El script cuenta con dos funciones de simulación (simular_trafico_y_estados y simular_latencias_y_tiempos). Debés eliminar estas funciones o su contenido y reemplazarlas por tu lógica de SRE real.

Ejemplo para Chequeos Web/Pings: Conectá tus bucles con librerías como requests o ejecuciones de subprocesos del sistema.

Ejemplo para Consultas: Insertá tus conectores de bases de datos o lecturas de archivos de configuración JSON.

Inyección de Datos: Aplicá los métodos de la librería según corresponda sobre tus variables:

.labels(label1="val").inc() para sumar eventos.

.labels(label1="val").set(valor_numerico) para actualizar estados.

with TU_HISTOGRAMA.labels(label1="val").time(): para envolver tus llamadas de red y medir su rendimiento automáticamente.

# 4. Requisitos e Instalación
Para ejecutar este exportador de métricas en cualquier entorno Linux / macOS / Windows, solo necesitás contar con Python 3 y su gestor de paquetes.

Instalar la librería cliente oficial de Prometheus:

```
pip install prometheus_client
```

Ejecutar el script:
```
python3 promttheus-exporter.py
```

Verificar la exposición local abriendo tu navegador o tirando un curl desde la consola:

```
curl http://localhost:9150/metrics
```
