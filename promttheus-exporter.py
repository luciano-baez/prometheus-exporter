#!/usr/bin/env python3
"""
2026-05-26 By Luciano
Ejemplo de como hacer un exporter de prometheus usanddo la lbreria prometheus_client
Este script contiene TODOS los tipos de métricas y patrones de exposición disponibles
en la librería oficial de Prometheus para Python.
"""

import time
import random
import threading
from prometheus_client import (
    start_http_server,
    Counter,
    Gauge,
    Histogram,
    Summary,
    Info,
    Enum,
    REGISTRY
)
# Importamos los recolectores de plataforma nativos (Métricas de Runtime)
from prometheus_client import ProcessCollector, PlatformCollector

# ==============================================================================
# 1. COUNTER (Contador Monotónicamente Creciente)
# ------------------------------------------------------------------------------
# ¿Qué es?: Un valor que SOLO puede subir o volver a 0 si el script se reinicia.
# ¿Qué genera en Prometheus?: Un único valor escalar que crece: `mi_metrica_total`.
# ¿Para qué sirve ?: Medir volumen y calcular tasas de transferencia (throughput).
#   - Total de peticiones HTTP.
#   - Cantidad de errores 5xx detectados.
#   - Volumen de bytes transmitidos.
# En Grafana NUNCA se grafica el Counter directo; se usa la función `rate()` o `increase()`.
# ==============================================================================
SOLICITUDES_PROCESADAS_TOTAL = Counter(
    'sre_solicitudes_procesadas_total', # Sufijo _total es una buena práctica
    'Cantidad total de solicitudes procesadas por el componente',
    ['componente', 'estado'] # Etiquetas para filtrar (ej: componente="auth", estado="200")
)

# ==============================================================================
# 2. GAUGE (Indicador de Nivel Instantáneo)
# ------------------------------------------------------------------------------
# ¿Qué es?: Un valor numérico que puede subir y bajar de forma arbitraria.
# ¿Qué genera en Prometheus?: Un único valor escalar en tiempo real: `mi_metrica`.
# ¿Para qué sirve ?: Medir utilización, saturación y capacidades actuales.
#   - Uso de memoria RAM o CPU (0% a 100%).
#   - Conexiones simultáneas activas en una Base de Datos.
#   - Cantidad de hilos (threads) vivos en el sistema.
#   - Latencia del último ping o chequeo web individual (como hacés en tu sintético).
# ==============================================================================
CONEXIONES_ACTIVAS = Gauge(
    'sre_conexiones_activas_simultaneas',
    'Cantidad de clientes conectados simultáneamente en este instante',
    ['nodo_id']
)

# ==============================================================================
# 3. HISTOGRAM (Distribución de Frecuencias por Rangos/Buckets)
# ------------------------------------------------------------------------------
# ¿Qué es?: Mide la duración o tamaño de eventos y los agrupa en buckets.
# ¿Qué genera en Prometheus?: Genera múltiples series temporales automáticamente:
#   - `mi_metrica_bucket{le="0.1"}` (Contador de eventos que tardaron <= 0.1s)
#   - `mi_metrica_bucket{le="0.5"}` (Contador de eventos que tardaron <= 0.5s)
#   - `mi_metrica_bucket{le="+Inf"}` (Total de eventos, equivalente al _count)
#   - `mi_metrica_sum` (La suma de todas las duraciones)
#   - `mi_metrica_count` (El total de eventos registrados)
# ¿Para qué sirve?: Medir el rendimiento frente a SLAs / SLOs. Es el mejor
# tipo de métrica para calcular percentiles agregados (p95, p99) de múltiples servers
# usando la función `histogram_quantile()` en PromQL.
# ==============================================================================
LATENCIA_HTTP_SEGUNDOS = Histogram(
    'sre_latencia_http_segundos',
    'Distribución de tiempos de respuesta de la API HTTP',
    ['metodo', 'ruta'],
    # Definimos los "cortes" de los baldes en segundos. Ajustar según tu SLA.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf"))
)

# ==============================================================================
# 4. SUMMARY (Percentiles calculados del lado del Cliente)
# ------------------------------------------------------------------------------
# ¿Qué es?: Al igual que el Histogram, mide duraciones o tamaños. La diferencia es
# que calcula los percentiles (quantiles) dentro del propio script de Python.
# ¿Qué genera en Prometheus?:
#   - `mi_metrica{quantile="0.5"}` (Mediana exacta)
#   - `mi_metrica{quantile="0.99"}` (Percentil 99 exacto)
#   - `mi_metrica_sum` y `mi_metrica_count`
# ¿Para qué sirve ?: Obtener percentiles muy exactos de un proceso específico
# sin saturar a Prometheus con cálculos. 
# DESVENTAJA CRÍTICA: No se pueden promediar ni agrupar matemáticamente entre distintos
# servidores en Grafana. Es "lo que ve este script y nada más".
# ==============================================================================
TIEMPO_QUERY_DB_SEGUNDOS = Summary(
    'sre_tiempo_query_db_segundos',
    'Tiempo de respuesta de consultas SQL con percentiles pre-calculados',
    ['operacion']
)

# ==============================================================================
# 5. INFO (Metadatos Estáticos)
# ------------------------------------------------------------------------------
# ¿Qué es?: Información en formato Clave-Valor que NO cambia durante la vida del proceso.
# ¿Qué genera en Prometheus?: Una métrica con valor fijo `1`, donde los datos reales
# viajan adentro de las etiquetas: `mi_metrica_info{version="1.0", env="prod"}=1`.
# ¿Para qué sirve ?: Cruzar datos en Grafana para auditorías o paneles informativos
# (ej: Mostrar en el Dashboard qué versión de software está corriendo).
# ==============================================================================
INFORMACION_SISTEMA = Info('sre_sistema_metadata', 'Metadatos estáticos de la aplicación')
INFORMACION_SISTEMA.info({'version': '3.4.2', 'entorno': 'produccion', 'cluster': 'ar-cordoba-01'})

# ==============================================================================
# 6. ENUM (Máquina de Estados)
# ------------------------------------------------------------------------------
# ¿Qué es?: Representa un estado textual de una lista cerrada de opciones.
# ¿Qué genera en Prometheus?: Una serie por cada estado posible con valor 0 o 1.
#   - `mi_metrica{sre_nodo_estado="ONLINE"}=1`
#   - `mi_metrica{sre_nodo_estado="MAINTENANCE"}=0`
# ¿Para qué sirve ?: Monitorear estados lógicos de pipelines, backups o servicios.
# ==============================================================================
ESTADO_NODO_VPN = Enum(
    'sre_nodo_vpn_estado',
    'Estado operativo actual del túnel VPN',
    ['proveedor'],
    states=['ONLINE', 'OFFLINE', 'DEGRADED', 'MAINTENANCE']
)


# ==============================================================================
# HILOS SIMULADORES (Generación de datos de prueba)
# ==============================================================================

def simular_trafico_y_estados():
    """Simula contadores, niveles variables y cambios de estado lógicos"""
    while True:
        # 1. Simulando CONTADORES (.inc())
        comp = random.choice(['api-gateway', 'auth-service', 'payment-v2'])
        status = random.choice(['200', '200', '200', '404', '500'])
        SOLICITUDES_PROCESADAS_TOTAL.labels(componente=comp, estado=status).inc()
        
        # 2. Simulando GAUGES (.set(), .inc(), .dec())
        # Seteamos un valor absoluto directo
        CONEXIONES_ACTIVAS.labels(nodo_id='srv-core-01').set(random.randint(40, 50))
        # Sumamos o restamos de forma relativa sobre el valor actual
        CONEXIONES_ACTIVAS.labels(nodo_id='srv-core-01').inc(random.randint(0, 2))
        CONEXIONES_ACTIVAS.labels(nodo_id='srv-core-01').dec(random.randint(0, 2))

        # 3. Simulando ENUMS (.state())
        estado_actual = random.choice(['ONLINE', 'ONLINE', 'ONLINE', 'DEGRADED'])
        ESTADO_NODO_VPN.labels(proveedor='arsat').state(estado_actual)

        time.sleep(1)

def simular_latencias_y_tiempos():
    """Simula telemetría basada en tiempo usando Histograms y Summaries"""
    while True:
        # 1. Simulación de HISTOGRAMA con Context Manager (.time())
        # El bloque 'with' mide automáticamente la duración exacta de lo que pasa adentro
        ruta_web = random.choice(['/index', '/api/v1/checkout', '/login'])
        with LATENCIA_HTTP_SEGUNDOS.labels(metodo='GET', ruta=ruta_web).time():
            # Simulamos un delay (el checkout es más pesado)
            delay_base = 0.3 if ruta_web == '/api/v1/checkout' else 0.01
            time.sleep(delay_base + random.uniform(0.005, 0.08))

        # 2. Simulación de SUMMARY usando observación manual (.observe())
        # Calculamos un tiempo de query simulado y se lo pasamos directo
        tipo_query = random.choice(['SELECT', 'UPDATE'])
        if tipo_query == 'SELECT':
            duracion_query = random.expovariate(25) # Media de ~0.04 segundos
        else:
            duracion_query = random.uniform(0.1, 0.4)
            
        TIEMPO_QUERY_DB_SEGUNDOS.labels(operacion=tipo_query).observe(duracion_query)

        time.sleep(0.5)


# ==============================================================================
# BLOQUE PRINCIPAL (Inicialización del Servidor)
# ==============================================================================
if __name__ == '__main__':
    PUERTO_EXPORTER = 9150
    print(f"[-] Inicializando Exporter SRE en el puerto {PUERTO_EXPORTER}...")

    # --------------------------------------------------------------------------
    # SOLUCIÓN: Limpieza y registro correcto de Métricas de Runtime
    # --------------------------------------------------------------------------
    # Guardamos los colectores por defecto instalados de fábrica para removerlos
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        if type(collector).__name__ in ['ProcessCollector', 'PlatformCollector']:
            REGISTRY.unregister(collector)

    # Registramos nuestras versiones customizadas de forma segura
    # ProcessCollector SÍ acepta 'namespace'
    ProcessCollector(namespace='sre_exporter_runtime', registry=REGISTRY)
    
    # PlatformCollector SOLO acepta 'registry' (fijate que le quitamos el namespace)
    PlatformCollector(registry=REGISTRY)

    # Iniciamos el servidor web que expone el endpoint /metrics
    start_http_server(PUERTO_EXPORTER)
    print(f"[+] Servidor HTTP levantado con éxito.")
    print(f"[+] Accedé a tus métricas en: http://localhost:{PUERTO_EXPORTER}/metrics")

    # Encendemos los hilos de simulación en segundo plano
    threading.Thread(target=simular_trafico_y_estados, daemon=True).start()
    threading.Thread(target=simular_latencias_y_tiempos, daemon=True).start()

    # Mantenemos vivo el hilo principal
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[-] SRE Exporter detenido correctamente por señal del usuario.")
