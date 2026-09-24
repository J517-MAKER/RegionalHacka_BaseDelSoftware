import asyncio
import logging
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from nicegui import ui
from nicegui.testing import user_simulation
from nicegui.storage import Storage


@asynccontextmanager
async def simulation():
    # NiceGUI's test reset expects these fixture flags even with unittest.
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'PYTEST_CURRENT_TEST':'unittest','NICEGUI_SCREEN_TEST_PORT':'8081'}), patch.object(Storage,'path',Path(directory)/'storage'), patch('config.AI_CONTEXT_ENABLED', False), patch('config.EVIDENCE_AUDIO_DIR',Path(directory)/'audio'), patch('config.EVIDENCE_VIDEO_DIR',Path(directory)/'video'):
        async with user_simulation(main_file=Path(__file__).resolve().parents[1]/'main.py') as user:
            yield user


def listen(phrases,camera_id='CAM-008'):
    """Drive the real pipeline with synthetic audio and scripted transcriptions."""
    import numpy as np
    import config
    from datetime import datetime
    from services.monitoring_service import MonitoringSession
    monitor=MonitoringSession(camera_id=camera_id,actor='Operador01')
    monitor.started_wall=datetime.now()
    rate,window=config.AUDIO_SAMPLE_RATE,int(config.AUDIO_WINDOW_SECONDS*config.AUDIO_SAMPLE_RATE)
    tone=(np.sin(np.arange(int((config.AUDIO_WINDOW_SECONDS+config.EVIDENCE_POST_SECONDS+1)*rate),dtype=np.float32)/rate*1130)*.2).astype(np.float32)
    for phrase in phrases:
        start=monitor.ring.written
        monitor.ring.write(tone)
        with patch('services.monitoring_service.transcribe_window',return_value=(phrase,{'segments':[{'text':phrase,'start':0,'end':1}]})):
            monitor._analyze(start,start+window,-1.)
    return monitor.results[0]


class ErrorCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages=[]

    def emit(self,record):
        self.messages.append(record.getMessage())


class DemoFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_monitoring_console_and_evidence_review(self):
        async with simulation() as user:
            from services import store
            from services.users_service import switch_demo_user
            await user.open('/voice')
            await user.should_see('SERVICIO DE DETECCIÓN')
            await user.should_see('INICIAR MONITOREO')
            with user:
                # Ordinary conversation leaves no evidence behind.
                normal=listen(['ayer comí tacos y se me atoró uno, ocupé ayuda'])
                self.assertEqual(normal['classification'],'NORMAL')
                self.assertEqual(store.evidence,[])
                result=listen(['qué dejaron de tarea','por favor déjame, me están siguiendo'])
            self.assertEqual(len(store.evidence),1)
            evidence=store.evidence[0]
            self.assertEqual(result['event_id'],evidence.event_id)

            await user.open('/alerts')
            user.find(ui.table).trigger('review',evidence.event_id)
            await user.should_see('CONFIRMAR PARA ATENCIÓN')
            await user.should_see('Archivo original verificado')
            await user.should_see('Pendiente de integración')
            with self.assertRaises(AssertionError):  # evidence is never deleted from the interface
                user.find('ELIMINAR')
            user.find('MARCAR FALSO POSITIVO').click()
            await asyncio.sleep(.2)
            self.assertEqual(evidence.review_status,'FALSO_POSITIVO')
            self.assertEqual(evidence.reviewed_by,'Operador01')
            self.assertTrue((Path(evidence.audio_file).name))

            user.find('SOLICITAR ELIMINACIÓN').click()
            await user.should_see('Solicitud de eliminación')
            user.find('Motivo de la solicitud').type('Se trataba de un ensayo escolar')
            user.find('Enviar solicitud').click()
            await asyncio.sleep(.2)
            self.assertEqual(evidence.review_status,'DELETION_REQUESTED')
            self.assertEqual(store.deletion_requests[0].requested_by,'Operador01')

            with user:
                switch_demo_user('USR-03')
            await user.open('/supervision')
            await user.should_see('Solicitudes de eliminación')
            user.find('APROBAR').click()
            await asyncio.sleep(.2)
            self.assertEqual(store.deletion_requests[0].status,'APPROVED')
            self.assertEqual(store.deletion_requests[0].reviewed_by,'Supervisor01')
            self.assertEqual(evidence.review_status,'DELETION_APPROVED')
            # For the prototype the original file is preserved after the approval.
            import config
            self.assertTrue((config.BASE_DIR/evidence.audio_file).exists())
            self.assertTrue(any('aprobó la solicitud' in log.description for log in store.logs))

    async def test_admin_assistant_is_restricted_and_navigates(self):
        async with simulation() as user:
            import numpy as np
            from services import store
            from services.users_service import switch_demo_user
            from services.voice_service import MicrophoneCapture

            await user.open('/monitor')
            with self.assertRaises(AssertionError):  # el operador no ve el asistente
                user.find(marker='assistant-button')

            with user:
                switch_demo_user('USR-04')
            await user.open('/monitor')
            user.find(marker='assistant-button')

            with patch.object(MicrophoneCapture, 'start', lambda self: None), \
                 patch.object(MicrophoneCapture, 'stop', lambda self: np.zeros(16000, dtype='float32')), \
                 patch('components.admin_voice_assistant.transcribe_audio',
                       return_value=('búscame el folio 184', {})):
                user.find(marker='assistant-button').click()
                await asyncio.sleep(.2)
                await user.should_see('Escuchando')
                user.find(marker='assistant-button').click()
                await asyncio.sleep(1.0)
                await user.should_see('búscame el folio 184')
                await user.should_see('Caso BUS-2026-0184 encontrado')
            entry=store.logs[0]
            self.assertEqual((entry.user,entry.kind,entry.result),('Admin01','Comando de voz','SUCCESS'))
            self.assertIn('OPEN_CASE',entry.description)
            await asyncio.sleep(1.4)
            await user.should_see('Detalle del caso')


    async def test_operator_sees_only_operational_tools(self):
        async with simulation() as user:
            await user.open('/monitor')
            for label in ['Centro de monitoreo','Casos de búsqueda','Cámaras','Reconocimiento en vivo',
                          'Coincidencias','Mapa y seguimiento','Alertas de auxilio','Detección de auxilio',
                          'Historial operativo']:
                user.find(label)
            for hidden in ['Usuarios y permisos','Configuración','Bandeja de supervisión','Auditoría completa']:
                with self.assertRaises(AssertionError):
                    user.find(hidden)
            with self.assertRaises(AssertionError):  # the assistant belongs to the administrator
                user.find(marker='assistant-button')
            # The operator asks for a deletion but never authorises one.
            await user.open('/alerts')
            with self.assertRaises(AssertionError):
                user.find('APROBAR')

    async def test_supervisor_works_from_the_supervision_tray(self):
        async with simulation() as user:
            from services.users_service import switch_demo_user
            from services.facial_service import request_review
            await user.open('/monitor')
            with user:
                # Escalating is the operator's move; the supervisor only resolves it.
                request_review('MAT-001')
                switch_demo_user('USR-03')
            await user.open('/')
            await user.should_see(content='Centro de supervisión',marker='page-title')
            for label in ['Bandeja de supervisión','Evidencia en revisión','Coincidencias en revisión',
                          'Solicitudes de eliminación','Auditoría operativa']:
                user.find(label)
            for hidden in ['Centro de monitoreo','Reconocimiento en vivo','Usuarios y permisos','Configuración']:
                with self.assertRaises(AssertionError):
                    user.find(hidden)
            with self.assertRaises(AssertionError):
                user.find(marker='assistant-button')
            # Operational tools stay closed even when the URL is typed by hand.
            for route in ('/live','/voice','/monitor','/cases/import-alert','/users','/settings'):
                await user.open(route)
                await user.should_see(content='Acceso restringido',marker='page-title')
            # A case may be consulted, but not created from here.
            await user.open('/cases')
            with self.assertRaises(AssertionError):
                user.find('Nueva búsqueda manual')
            with user:
                with self.assertRaises(PermissionError):
                    from services.cases_service import create_case
                    create_case({'name':'Intento de supervisor'})
                with self.assertRaises(PermissionError):  # a supervisor cannot escalate to themselves
                    request_review('MAT-002')
            await user.open('/supervision')
            await user.should_see('Pendientes de revisión')
            await user.should_see('MAT-001')

    async def test_administrator_administers_and_reads(self):
        async with simulation() as user:
            from services.users_service import switch_demo_user
            await user.open('/monitor')
            with user:
                switch_demo_user('USR-04')
            await user.open('/')
            await user.should_see(content='Usuarios y permisos',marker='page-title')
            for label in ['Usuarios y permisos','Configuración','Auditoría completa']:
                user.find(label)
            for hidden in ['Centro de monitoreo','Reconocimiento en vivo','Detección de auxilio',
                           'Bandeja de supervisión']:
                with self.assertRaises(AssertionError):
                    user.find(hidden)
            user.find(marker='assistant-button')  # the assistant is the administrator's tool
            # Operating a camera or the microphone is not an administrative task.
            for route in ('/live','/voice','/supervision','/monitor'):
                await user.open(route)
                await user.should_see(content='Acceso restringido',marker='page-title')
            # Pages the assistant navigates to open in read-only mode.
            await user.open('/cases/BUS-2026-0184')
            await user.should_see(content='Detalle del caso',marker='page-title')
            with self.assertRaises(AssertionError):
                user.find('Añadir referencia de prueba')
            await user.open('/matches?match_id=MAT-001')
            for hidden in ['Validar como posible coincidencia','Descartar','Solicitar revisión']:
                with self.assertRaises(AssertionError):
                    user.find(hidden)
            await user.open('/alerts')
            with self.assertRaises(AssertionError):
                user.find('CONFIRMAR PARA ATENCIÓN')
            await user.open('/history')
            await user.should_see(content='Auditoría completa',marker='page-title')

    async def test_operator_demo_end_to_end(self):
        collector=ErrorCollector()
        logging.getLogger().addHandler(collector)
        try:
            async with simulation() as user:
                from services import store
                from services.users_service import switch_demo_user,update_user
                from services.cases_service import create_case,photo_data_url

                for route,title in [('/monitor','Centro de monitoreo'),('/cases','Casos de búsqueda'),
                                    ('/cases/BUS-2026-0184','Detalle del caso'),
                                    ('/cases/import-alert','Importar alerta de búsqueda'),('/cameras','Red de cámaras'),
                                    ('/live','Reconocimiento facial en vivo'),
                                    ('/matches','Revisión de coincidencias'),('/tracking','Mapa y seguimiento'),
                                    ('/alerts','Revisión de evidencia'),('/voice','Detección de auxilio por voz'),
                                    ('/history','Historial operativo')]:
                    await user.open(route)
                    await user.should_see(content=title,marker='page-title')

                # Administration and supervision are other people's jobs: typing the URL is not enough.
                for route in ('/users','/settings','/supervision'):
                    await user.open(route)
                    await user.should_see(content='Acceso restringido',marker='page-title')

                await user.open('/cases')
                user.find('Buscar nombre o folio').type('sin coincidencias de prueba')
                await user.should_see('No hay registros para los filtros seleccionados.')
                user.find('Buscar nombre o folio').clear()
                await user.should_see('Crear caso desde alerta')
                user.find('Nueva búsqueda manual').click()
                user.find('Nombre completo *').type('Persona de prueba QA')
                user.find('Registrar caso y procesar referencias').click()
                await asyncio.sleep(.2)
                await user.should_see('Persona de prueba QA')
                self.assertEqual(store.cases[-1].person.name,'Persona de prueba QA')
                self.assertEqual(store.cases[-1].reference_status,'Sin referencia fotográfica')

                await user.open('/matches?match_id=MAT-001')
                user.find('Validar como posible coincidencia').click()
                self.assertEqual(store.matches[0].reviewed_by,'Operador01')
                self.assertEqual(store.detections[0].status,'Validada por operador')
                await user.should_see('Revisión registrada: Operador01')
                user.find('Descartar').click()
                self.assertEqual(store.detections[0].status,'Descartada')
                user.find('Solicitar revisión').click()
                self.assertEqual(store.matches[0].status,'En revisión')

                await user.open('/cameras?camera_id=CAM-010')
                await user.should_see('Conexión perdida.')
                user.find('Reintentar conexión').click()
                await user.should_see('No fue posible conectar con la cámara.')

                with user:
                    listen(['vamos saliendo de clase','suéltame, ayuda'])
                self.assertEqual(store.voice_events[0].intent,'SOLICITUD_AUXILIO')
                evidence=store.evidence[0]
                alert=store.alerts[0]

                await user.open('/alerts')
                user.find(ui.table).trigger('review',evidence.event_id)
                await user.should_see('CONFIRMAR PARA ATENCIÓN')
                user.find('CONFIRMAR PARA ATENCIÓN').click()
                await asyncio.sleep(.2)
                self.assertEqual(evidence.review_status,'CONFIRMADO_PARA_ATENCION')
                self.assertEqual(evidence.reviewed_by,'Operador01')
                user.find('Iniciar seguimiento').click()
                await asyncio.sleep(.2)
                self.assertTrue(alert.tracking_requested)
                self.assertFalse(alert.tracking_started)
                await user.should_see('Módulo de seguimiento pendiente de integración.')

                with user:
                    with self.assertRaises(PermissionError):
                        update_user('USR-02','Supervisor','Activo')
                    with self.assertRaises(ValueError):
                        create_case({'name':''})
                    with self.assertRaises(ValueError):
                        photo_data_url(b'not an image','image/png')
                    switch_demo_user('USR-04')
                await user.open('/users')
                user.find(ui.table).trigger('edit','USR-02')
                await user.should_see('Permisos / Operador02')
                with user:
                    update_user('USR-02','Supervisor','Activo')
                    with self.assertRaises(ValueError):
                        update_user('USR-04','Operador','Activo')
                self.assertEqual(store.users[1].role,'Supervisor')
                self.assertTrue(any(log.kind=='Permisos' for log in store.logs))
                await user.open('/cases/no-existe')
                await user.should_see('No se encontró este expediente.')
                await asyncio.sleep(.2)
            self.assertEqual(collector.messages,[])
        finally:
            logging.getLogger().removeHandler(collector)


if __name__=='__main__':
    unittest.main()
