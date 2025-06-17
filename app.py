import os
import io
import streamlit as st
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from st_audiorecorder import st_audiorecorder # ### NOWOŚĆ ### Importujemy bibliotekę do nagrywania

# --- Konfiguracja Aplikacji (bez zmian) ---
DRIVE_FILE_NAME = "historia_czatu_drive.txt"
SCOPES = ["https://www.googleapis.com/auth/drive"]

# --- Funkcje Pomocnicze dla Google Drive (bez zmian) ---
@st.cache_resource
def get_drive_service():
    # ... (cała funkcja bez zmian)
    try:
        creds_info = {
            "type": st.secrets.gcp_service_account.type, "project_id": st.secrets.gcp_service_account.project_id,
            "private_key_id": st.secrets.gcp_service_account.private_key_id, "private_key": st.secrets.gcp_service_account.private_key.replace('\\n', '\n'),
            "client_email": st.secrets.gcp_service_account.client_email, "client_id": st.secrets.gcp_service_account.client_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": st.secrets.gcp_service_account.client_x509_cert_url,
            "universe_domain": "googleapis.com"
        }
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        return service
    except Exception as e:
        st.error(f"Błąd podczas łączenia z Google Drive: {e}")
        st.error("Sprawdź, czy wszystkie wartości w sekcji [gcp_service_account] w 'Secrets' są poprawnie wklejone.")
        return None

def get_file_id(service, file_name):
    # ... (cała funkcja bez zmian)
    query = f"name='{file_name}' and trashed=false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    return files[0].get('id') if files else None

def download_history(service, file_id):
    # ... (cała funkcja bez zmian)
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return fh.getvalue().decode('utf-8')
    except HttpError:
        return ""

def upload_history(service, file_id, file_name, content_to_save):
    # ... (cała funkcja bez zmian)
    try:
        media = MediaIoBaseUpload(io.BytesIO(content_to_save.encode('utf-8')),
                                  mimetype='text/plain',
                                  resumable=True)
        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_metadata = {'name': file_name, 'mimeType': 'text/plain'}
            response = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            st.session_state.file_id = response.get('id')
    except HttpError as error:
        if error.resp.status == 404:
            st.warning(f"Wystąpił błąd 404 (plik nie znaleziony) dla ID: {file_id}. Spróbuję utworzyć nowy plik.")
            upload_history(service, None, file_name, content_to_save)
        else:
            st.error(f"Wystąpił błąd podczas operacji na Google Drive: {error}")
    except Exception as e:
        st.error(f"Wystąpił nieoczekiwany błąd podczas przesyłania historii: {e}")

# --- Główna Logika Aplikacji Streamlit ---

st.set_page_config(page_title="Gemini z Pamięcią", page_icon="🎤", layout="wide")

st.image("moje_logo.png", width=48)
st.image("baner.png", width=200)
st.title("🧠 Gemini z Pamięcią i Głosem")
st.caption("Mów lub pisz. Twoja prywatna rozmowa z AI jest zapisywana na Twoim Dysku Google.")

# --- Inicjalizacja API, Stanu Sesji i Historii (bez zmian) ---
# ... (cała sekcja inicjalizacji, tak jak w poprzedniej wersji kodu, pozostaje bez zmian)
try:
    genai.configure(api_key=st.secrets.GEMINI_API_KEY)
except Exception as e:
    st.error(f"Błąd konfiguracji Gemini API. Sprawdź swój klucz w Secrets. Błąd: {e}")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "gemini_history" not in st.session_state:
    st.session_state.gemini_history = []
if "history_loaded" not in st.session_state:
    with st.spinner("Łączenie i wczytywanie pamięci z Dysku Google..."):
        drive_service = get_drive_service()
        if drive_service:
            st.session_state.drive_service = drive_service
            file_id = get_file_id(drive_service, DRIVE_FILE_NAME)
            st.session_state.file_id = file_id
            if file_id:
                history_text = download_history(drive_service, file_id)
                if history_text:
                    gemini_history_from_drive = []
                    turns = history_text.strip().split('\n\n\n')
                    for turn in turns:
                        if 'Ty:' in turn and 'Gemini:' in turn:
                            user_part = turn.split('Ty:')[1].split('Gemini:')[0].strip()
                            model_part = turn.split('Gemini:')[1].strip()
                            gemini_history_from_drive.append({'role': 'user', 'parts': [user_part]})
                            gemini_history_from_drive.append({'role': 'model', 'parts': [model_part]})
                    st.session_state.gemini_history = gemini_history_from_drive
            st.success("Pamięć połączona i wczytana w tle!")
        else:
            st.error("Nie udało się połączyć z usługą Dysku Google.")
            st.stop()
    st.session_state.history_loaded = True

if "gemini_chat" not in st.session_state:
    model = genai.GenerativeModel('gemini-1.5-flash')
    st.session_state.gemini_chat = model.start_chat(history=st.session_state.gemini_history)

# --- Wyświetlanie Historii Czatu w Interfejsie (bez zmian) ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ### NOWOŚĆ ### - OBSŁUGA GŁOSU I TEKSTU
st.markdown("---")
st.write("Naciśnij przycisk mikrofonu, aby mówić, lub wpisz tekst poniżej:")

# Dzielimy interfejs na dwie kolumny dla lepszego wyglądu
col1, col2 = st.columns([1, 4]) 

with col1:
    # Wyświetlamy widżet do nagrywania audio.
    # `key` jest ważny, aby Streamlit wiedział, że to ten sam element.
    audio_bytes = st_audiorecorder(key="audio_recorder")

with col2:
    # Pole do wpisywania tekstu
    text_prompt = st.text_input("...lub wpisz swoje pytanie tutaj:", key="text_input")

# Sprawdzamy, czy użytkownik dostarczył dane (głosowe LUB tekstowe)
user_prompt = None
prompt_display = None # Co wyświetlić w dymku czatu

if audio_bytes:
    # Mamy nagranie audio
    st.info("Przetwarzam Twoje nagranie...")
    # Gemini 1.5 potrafi przetworzyć surowe bajty audio!
    user_prompt = {"mime_type": "audio/wav", "data": audio_bytes}
    # Możemy spróbować od razu przetworzyć audio na tekst do wyświetlenia (opcjonalnie)
    # W prostszej wersji po prostu napiszemy, że to było polecenie głosowe.
    prompt_display = "🎤 *Twoje polecenie głosowe*"

elif text_prompt:
    # Mamy tekst
    user_prompt = text_prompt
    prompt_display = text_prompt


# --- Główna pętla czatu, jeśli jest nowe polecenie ---
if user_prompt:
    # Wyświetl polecenie użytkownika
    st.session_state.messages.append({"role": "user", "content": prompt_display})
    with st.chat_message("user"):
        st.markdown(prompt_display)

    # Wyślij do Gemini i uzyskaj odpowiedź
    with st.chat_message("assistant"):
        with st.spinner("Myślę..."):
            try:
                # `send_message` przyjmuje zarówno tekst, jak i obiekty z danymi (jak nasze audio)
                response = st.session_state.gemini_chat.send_message(user_prompt)
                st.markdown(response.text)
                
                # Dodaj odpowiedź do historii UI
                st.session_state.messages.append({"role": "assistant", "content": response.text})

                # --- Zapisywanie Pełnej Historii do Dysku Google (logika bez zmian) ---
                full_history_to_save = ""
                chat_history_from_model = st.session_state.gemini_chat.history
                
                for i in range(0, len(chat_history_from_model), 2):
                    if i + 1 < len(chat_history_from_model):
                        user_msg = chat_history_from_model[i].parts[0].text
                        assistant_msg = chat_history_from_model[i+1].parts[0].text
                        full_history_to_save += f"Ty: {user_msg}\n\nGemini: {assistant_msg}\n\n\n"
                
                if st.session_state.get("drive_service"):
                    upload_history(st.session_state.drive_service, st.session_state.get("file_id"), DRIVE_FILE_NAME, full_history_to_save)

            except Exception as e:
                st.error(f"Wystąpił błąd: {e}")
    
    # Wyczyść pola wejściowe, aby uniknąć ponownego wysłania tego samego polecenia
    st.session_state.text_input = ""
    # Niestety, nie ma prostego sposobu na programowe zresetowanie st_audiorecorder,
    # ale ponowne uruchomienie po przetworzeniu powinno pomóc.
    st.rerun()