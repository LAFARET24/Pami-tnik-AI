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
DRIVE_FILE_NAME = "notes_git_data.txt" # Możesz zmienić na "moj_pamietnik.txt", jeśli chcesz
SCOPES = ["https://www.googleapis.com/auth/drive"]

# --- OSTATECZNA FUNKCJA LOGOWANIA DLA "ROBOTA" ---
@st.cache_resource
def get_drive_service():
    try:
        # Tworzymy słownik z danych logowania, pobierając każdą wartość osobno z sekretów
        creds_info = {
            "type": st.secrets.gcp_service_account.type,
            "project_id": st.secrets.gcp_service_account.project_id,
            "private_key_id": st.secrets.gcp_service_account.private_key_id,
            # Ta linijka naprawia problem ze znakami nowej linii w kluczu prywatnym
            "private_key": st.secrets.gcp_service_account.private_key.replace('\\n', '\n'),
            "client_email": st.secrets.gcp_service_account.client_email,
            "client_id": st.secrets.gcp_service_account.client_id,
            "auth_uri": st.secrets.gcp_service_account.auth_uri,
            "token_uri": st.secrets.gcp_service_account.token_uri,
            "auth_provider_x509_cert_url": st.secrets.gcp_service_account.auth_provider_x509_cert_url,
            "client_x509_cert_url": st.secrets.gcp_service_account.client_x509_cert_url,
            "universe_domain": st.secrets.gcp_service_account.universe_domain
        }
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        return service
    except Exception as e:
        st.error(f"Błąd logowania przez Service Account: {e}")
        st.error("Sprawdź, czy wszystkie pola w [gcp_service_account] w 'Secrets' są poprawnie wklejone.")
        return None

# Reszta funkcji bez zmian...
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
        print(f"Błąd gTTS: {e}")
        return None

# --- Główna logika aplikacji Streamlit ---
st.set_page_config(page_title="Pamiętnik AI", page_icon="📝")
st.title("📝 Pamiętnik AI")
st.caption("Twój inteligentny pamiętnik zasilany przez AI.")

try:
    genai.configure(api_key=st.secrets.GEMINI_API_KEY)
except Exception as e:
    st.error(f"Błąd konfiguracji Gemini API: {e}")
    st.stop()

drive_service = get_drive_service()
if not drive_service:
    st.stop()

if "file_id" not in st.session_state:
    with st.spinner("Sprawdzanie archiwum na Dysku Google..."):
        st.session_state.file_id = get_file_id(drive_service, DRIVE_FILE_NAME)

st.success("Połączono z Twoim prywatnym archiwum na Dysku Google.")
model = genai.GenerativeModel('gemini-1.5-flash')

def handle_prompt(prompt_text):
    with st.chat_message("user"):
        st.markdown(prompt_text)

    keywords_save = ["zapisz", "zanotuj", "notatka", "pamiętaj"]
    is_saving = any(keyword in prompt_text.lower() for keyword in keywords_save)

    with st.chat_message("assistant"):
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
                        f"Oto notatki:\n{notes_content}\n\nPYTANIE: {prompt_text}"
                    )
                    response = model.generate_content(system_prompt)
                    response_text = response.text
            
            st.markdown(response_text)
            sound_file = text_to_audio(response_text)
            if sound_file:
                st.audio(sound_file, autoplay=True)

st.write("Naciśnij i mów, aby dodać notatkę głosową lub zadać pytanie:")
audio_data = mic_recorder(start_prompt="▶️ Mów", stop_prompt="⏹️ Stop", just_once=True, key='mic1')

if audio_data and audio_data['bytes']:
    audio_bytes = audio_data['bytes']
    with st.spinner("Rozpoznaję mowę..."):
        audio_file = {"mime_type": "audio/wav", "data": audio_bytes}
        prompt_from_voice = genai.GenerativeModel('gemini-1.5-flash').generate_content(["Zamień tę mowę na tekst: ", audio_file]).text
        handle_prompt(prompt_from_voice)

if prompt_from_text := st.chat_input("...lub napisz tutaj"):
    handle_prompt(prompt_from_text)