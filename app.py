import os
import io
import datetime
import json
import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from streamlit_mic_recorder import mic_recorder
from gtts import gTTS

# --- Konfiguracja ---
DRIVE_FILE_NAME = "pamietnik_ai_data.txt" # Nowa nazwa pliku na notatki
SCOPES = ["https://www.googleapis.com/auth/drive"]

# --- Funkcja logowania dla "Robota" ---
@st.cache_resource
def get_drive_service():
    try:
        creds_info = dict(st.secrets.gcp_service_account)
        creds_info['private_key'] = creds_info['private_key'].replace('\\n', '\n')
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        return service
    except Exception as e:
        st.error(f"Błąd logowania przez Service Account: {e}")
        st.error("Sprawdź, czy sekrety w Streamlit Cloud są poprawnie wklejone.")
        return None

# --- Funkcje do obsługi plików ---
def get_file_id(service, file_name):
    query = f"name='{file_name}' and trashed=false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    return files[0].get('id') if files else None

def download_notes(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return fh.getvalue().decode('utf-8')
    except HttpError: return ""

def upload_notes(service, file_id, file_name, new_note_content):
    existing_content = ""
    if file_id:
        existing_content = download_notes(service, file_id)
    full_content = existing_content.strip() + f"\n\n{new_note_content}"
    media = MediaIoBaseUpload(io.BytesIO(full_content.encode('utf-8')), mimetype='text/plain', resumable=True)
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': file_name}
        response = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        st.session_state.file_id = response.get('id')

def text_to_audio(text):
    try:
        tts = gTTS(text=text, lang='pl')
        audio_fp = io.BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        return audio_fp
    except Exception as e:
        st.error(f"Błąd podczas generowania mowy: {e}")
        return None

# --- Główna logika aplikacji Streamlit ---
st.set_page_config(page_title="Pamiętnik AI", page_icon="📝")
st.title("📝 Pamiętnik AI")
st.caption("Twój inteligentny pamiętnik zasilany przez AI.")

# Inicjalizacja usług
try:
    genai.configure(api_key=st.secrets.GEMINI_API_KEY)
    drive_service = get_drive_service()
    if not drive_service:
        st.stop()
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"Błąd inicjalizacji: {e}. Sprawdź swoje sekrety w Streamlit Cloud.")
    st.stop()

if "file_id" not in st.session_state:
    with st.spinner("Sprawdzanie archiwum na Dysku Google..."):
        st.session_state.file_id = get_file_id(drive_service, DRIVE_FILE_NAME)

st.success("Połączono z Twoim prywatnym archiwum na Dysku Google.")

def handle_prompt(prompt_text):
    st.session_state.messages.append({"role": "user", "content": prompt_text})

    keywords_save = ["zapisz", "zanotuj", "notatka", "pamiętaj"]
    is_saving = any(keyword in prompt_text.lower() for keyword in keywords_save)
    
    with st.spinner("Przetwarzam..."):
        if is_saving:
            today_date = datetime.date.today().strftime("%Y-%m-%d")
            new_note_entry = f"[DATA: {today_date}]\n{prompt_text}\n---"
            upload_notes(drive_service, st.session_state.get("file_id"), DRIVE_FILE_NAME, new_note_entry)
            response_text = "Notatka została zapisana w Twoim archiwum."
        else:
            notes_content = ""
            if st.session_state.get("file_id"):
                notes_content = download_notes(drive_service, st.session_state.get("file_id"))
            if not notes_content.strip():
                response_text = "Twoje archiwum jest jeszcze puste. Zapisz pierwszą notatkę!"
            else:
                system_prompt = (
                    "Jesteś asystentem, który odpowiada na pytania wyłącznie na podstawie dostarczonych notatek z pamiętnika. "
                    f"Oto notatki:\n{notes_content}\n\nPYTANIE UŻYTKOWNIKA: {prompt_text}"
                )
                response = model.generate_content(system_prompt)
                response_text = response.text
        
        st.session_state.messages.append({"role": "assistant", "content": response_text})
        sound_file = text_to_audio(response_text)
        if sound_file:
            st.session_state.audio_to_play = sound_file

# Zarządzanie historią i interfejsem
if "messages" not in st.session_state:
    st.session_state.messages = []
if "audio_to_play" not in st.session_state:
    st.session_state.audio_to_play = None

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Odtwarzaj dźwięk, jeśli jest w kolejce i wyczyść go
if st.session_state.audio_to_play:
    st.audio(st.session_state.audio_to_play, autoplay=True)
    st.session_state.audio_to_play = None

# Wejście głosowe
st.write("Naciśnij i mów, aby dodać notatkę lub zadać pytanie:")
audio_data = mic_recorder(start_prompt="▶️ Mów", stop_prompt="⏹️ Stop", just_once=True, key='mic1')

if audio_data and audio_data['bytes']:
    audio_bytes = audio_data['bytes']
    with st.spinner("Rozpoznaję mowę..."):
        audio_file = {"mime_type": "audio/wav", "data": audio_bytes}
        prompt_from_voice = genai.GenerativeModel('gemini-1.5-flash').generate_content(["Zamień tę mowę na tekst: ", audio_file]).text
        handle_prompt(prompt_from_voice)
        st.rerun() # Odśwież, żeby od razu pokazać odpowiedź

# Wejście tekstowe
if prompt_from_text := st.chat_input("...lub napisz tutaj"):
    handle_prompt(prompt_from_text)
    st.rerun() # Odśwież, żeby od razu pokazać odpowiedź