"""Módulo central de inteligencia (LLM local)."""

import logging
from typing import List, Dict

try:
    import ollama
except ImportError:
    ollama = None

logger = logging.getLogger(__name__)

class ViernesBrain:
    """
    Cerebro cognitivo de Viernes utilizando Ollama de forma local.
    Gestiona el contexto de la conversación, el System Prompt y 
    limita el historial para mantener la eficiencia de memoria.
    """
    def __init__(self, model_name: str = "llama3.1", max_history: int = 5):
        """
        :param model_name: Nombre del modelo en Ollama (ej. 'llama3.1', 'phi3').
        :param max_history: Cantidad de interacciones (Pregunta+Respuesta) a recordar.
        """
        self.model_name = model_name
        self.max_history_messages = max_history * 2
        
        self.system_prompt = {
            "role": "system",
            "content": (
                "Eres Viernes, una asistente de IA interactiva, tecnológica y amigable para el fotomaton 'Kippu'. "
                "Tu trabajo es interactuar con el público en una presentación escolar, respondiendo "
                "de manera concisa y educada. "
                "Contexto técnico fundamental del proyecto que debes conocer: "
                "El grupo ha desarrollado un proyecto de e-commerce llamado 'CrumbSkate'. "
                "CrumbSkate está construido con las siguientes tecnologías: "
                "1. Frontend: React. "
                "2. Backend: Node.js (con Express). "
                "3. Base de Datos: MySQL. "
                "Si los usuarios te preguntan sobre el e-commerce o las tecnologías usadas, "
                "explícalo de forma entusiasta y sencilla. "
                "Regla vital: Responde SIEMPRE en español y sé muy breve (1 a 3 oraciones máximo) "
                "para que la conversación hablada fluya rápido."
            )
        }
        
        self.conversation_history: List[Dict[str, str]] = [self.system_prompt]
        logger.info(f"ViernesBrain inicializado apuntando al modelo local: {self.model_name}")

    def think(self, user_text: str) -> str:
        """
        Envía el texto del usuario al modelo local y devuelve la respuesta generada.
        Se encarga de podar el historial automáticamente si este excede el límite.
        """
        if ollama is None:
            logger.error("La librería 'ollama' no está instalada.")
            return "Error de sistema: No se detecta el motor de razonamiento lógico."
            
        self.conversation_history.append({"role": "user", "content": user_text})
        
        if len(self.conversation_history) > self.max_history_messages + 1:
            self.conversation_history = [self.conversation_history[0]] + self.conversation_history[-self.max_history_messages:]
            
        try:
            logger.info(f"Enviando consulta a Ollama ({self.model_name})...")
            response = ollama.chat(
                model=self.model_name,
                messages=self.conversation_history
            )
            
            ai_text = response['message']['content']
            self.conversation_history.append({"role": "assistant", "content": ai_text})
            return ai_text
            
        except Exception as e:
            logger.error(f"Error conectando con el servicio local de Ollama: {e}")
            if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                self.conversation_history.pop()
                
            return "Lo siento, mis sistemas cognitivos locales están desconectados. Asegúrate de que Ollama esté corriendo."


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("=========================================================")
    print(" Iniciando ViernesBrain (Modo Pruebas en Terminal)")
    print(" Asegúrate de tener Ollama ejecutándose en segundo plano.")
    print(" Si no tienes el modelo, corre: 'ollama pull llama3.1'")
    print(" Escribe 'salir' o presiona Ctrl+C para terminar.")
    print("=========================================================\n")
    
    # Si tu procesador Ryzen 5700G sufre con llama3.1, puedes cambiar el 
    # parámetro por model_name="phi3" (que es más pequeño y rápido en CPU).
    brain = ViernesBrain(model_name="llama3.1")
    
    try:
        while True:
            # Recibir input del usuario en consola
            user_input = input("\n[Tú]: ")
            if user_input.strip().lower() in ["salir", "quit", "exit"]:
                break
                
            if not user_input.strip():
                continue
                
            print("[Viernes está pensando...]")
            
            # Procesar el pensamiento
            respuesta = brain.think(user_input)
            
            print(f"\n[VIERNES]: {respuesta}")
            
    except KeyboardInterrupt:
        print("\nInterrupción manual detectada.")
    finally:
        print("\nCerebro apagado de manera segura.")
