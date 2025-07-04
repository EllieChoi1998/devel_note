import sqlite3
import asyncio
import threading
import os
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
import signal
import sys

class ChatDatabase:
    def __init__(self):
        self.db_path = './sqlite.db'
        self.current_chatroom_id = None
        self.connection = None
    
    def initialize_database(self):
        """데이터베이스 초기화"""
        db_exists = os.path.exists(self.db_path)
        
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row  # dict-like access
        
        if not db_exists:
            print("새로운 SQLite 데이터베이스를 생성합니다...")
            self.create_tables()
            return False  # 새 DB
        else:
            print("기존 SQLite 데이터베이스를 발견했습니다.")
            self.migrate_database()  # 기존 DB 마이그레이션
            return True  # 기존 DB
    
    def migrate_database(self):
        """기존 데이터베이스 마이그레이션 (필요한 컬럼 추가)"""
        cursor = self.connection.cursor()
        
        try:
            # response 테이블에 image_path 컬럼이 있는지 확인
            cursor.execute("PRAGMA table_info(response)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'image_path' not in columns:
                print("response 테이블에 image_path 컬럼을 추가합니다...")
                cursor.execute("ALTER TABLE response ADD COLUMN image_path TEXT")
                self.connection.commit()
                print("image_path 컬럼이 추가되었습니다.")
            else:
                print("데이터베이스가 이미 최신 상태입니다.")
                
        except Exception as e:
            print(f"데이터베이스 마이그레이션 중 오류: {e}")
    
    def create_tables(self):
        """테이블 생성"""
        cursor = self.connection.cursor()
        
        queries = [
            """CREATE TABLE chatroom (
                id INTEGER PRIMARY KEY AUTOINCREMENT
            )""",
            """CREATE TABLE chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                chatroom_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chatroom_id) REFERENCES chatroom(id)
            )""",
            """CREATE TABLE response (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                chat_id INTEGER,
                image_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chat(id)
            )"""
        ]
        
        for query in queries:
            cursor.execute(query)
        
        self.connection.commit()
        print("모든 테이블이 생성되었습니다.")
    
    def get_chatrooms(self):
        """채팅방 리스트 가져오기"""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT c.id, COUNT(ch.id) as message_count, 
                   MAX(ch.created_at) as last_activity
            FROM chatroom c
            LEFT JOIN chat ch ON c.id = ch.chatroom_id
            GROUP BY c.id
            ORDER BY last_activity DESC
        """)
        return cursor.fetchall()
    
    def create_chatroom(self):
        """새 채팅방 생성"""
        cursor = self.connection.cursor()
        cursor.execute('INSERT INTO chatroom DEFAULT VALUES')
        self.connection.commit()
        return cursor.lastrowid
    
    def save_message(self, message, chatroom_id):
        """메시지 저장"""
        cursor = self.connection.cursor()
        cursor.execute(
            'INSERT INTO chat (message, chatroom_id) VALUES (?, ?)',
            (message, chatroom_id)
        )
        self.connection.commit()
        return cursor.lastrowid
    
    def save_response(self, response_message, chat_id, image_path=None):
        """응답 저장 (이미지 경로 포함)"""
        cursor = self.connection.cursor()
        cursor.execute(
            'INSERT INTO response (message, chat_id, image_path) VALUES (?, ?, ?)',
            (response_message, chat_id, image_path)
        )
        self.connection.commit()
        return cursor.lastrowid
    
    def create_chatroom_folder(self, chatroom_id):
        """채팅방별 폴더 생성"""
        folder_path = Path(f"./chatroom_{chatroom_id}")
        folder_path.mkdir(exist_ok=True)
        return folder_path
    
    def get_next_image_number(self, chatroom_id, module_name):
        """해당 채팅방에서 특정 모듈의 다음 이미지 번호 조회"""
        folder_path = Path(f"./chatroom_{chatroom_id}")
        if not folder_path.exists():
            return 1
        
        # 해당 모듈명으로 시작하는 파일들 찾기
        existing_files = list(folder_path.glob(f"{module_name}_*.jpeg"))
        if not existing_files:
            return 1
        
        # 파일명에서 숫자 추출해서 최대값 + 1 반환
        numbers = []
        for file in existing_files:
            try:
                # {module_name}_{숫자}.jpeg에서 숫자 추출
                name_without_ext = file.stem  # 확장자 제거
                number_part = name_without_ext.split('_')[-1]  # 마지막 언더스코어 뒤의 숫자
                numbers.append(int(number_part))
            except (ValueError, IndexError):
                continue
        
        return max(numbers) + 1 if numbers else 1
    
    def move_and_rename_image(self, original_filename, chatroom_id, module_name):
        """이미지를 채팅방 폴더로 이동하고 이름 변경"""
        try:
            # 원본 파일 경로
            original_path = Path(f"./{original_filename}")
            
            if not original_path.exists():
                print(f"원본 파일을 찾을 수 없습니다: {original_path}")
                return None
            
            # 채팅방 폴더 생성
            folder_path = self.create_chatroom_folder(chatroom_id)
            
            # 다음 이미지 번호 조회
            next_number = self.get_next_image_number(chatroom_id, module_name)
            
            # 새 파일명 생성
            new_filename = f"{module_name}_{next_number}.jpeg"
            new_path = folder_path / new_filename
            
            # 파일 이동 및 이름 변경
            shutil.move(str(original_path), str(new_path))
            
            # 절대 경로 반환
            absolute_path = new_path.resolve()
            print(f"이미지 이동 완료: {original_path} -> {absolute_path}")
            
            return str(absolute_path)
            
        except Exception as e:
            print(f"이미지 이동 중 오류 발생: {e}")
            return None
    
    def save_response_with_image(self, response_message, chat_id, chatroom_id, original_image_filename, module_name):
        """응답과 이미지를 함께 저장"""
        try:
            # 이미지가 있는 경우 이동 처리
            image_path = None
            if original_image_filename:
                image_path = self.move_and_rename_image(
                    original_image_filename, 
                    chatroom_id, 
                    module_name
                )
            
            # 응답 저장 (이미지 경로 포함)
            response_id = self.save_response(response_message, chat_id, image_path)
            
            return {
                "response_id": response_id,
                "image_path": image_path,
                "success": True
            }
            
        except Exception as e:
            print(f"응답 저장 중 오류: {e}")
            return {
                "response_id": None,
                "image_path": None,
                "success": False,
                "error": str(e)
            }
    
    def get_user_input_with_timeout(self, question, timeout_seconds=30):
        """30초 타임아웃으로 사용자 입력 받기"""
        result = {"input": None, "timeout": False}
        
        def get_input():
            try:
                result["input"] = input(question).strip()
            except (EOFError, KeyboardInterrupt):
                result["input"] = None
        
        thread = threading.Thread(target=get_input)
        thread.daemon = True
        thread.start()
        thread.join(timeout_seconds)
        
        if thread.is_alive():
            result["timeout"] = True
            print(f"\n시간 초과! 새로운 채팅방을 생성합니다...")
            return None
        
        return result["input"]
    
    def select_or_create_chatroom(self):
        """채팅방 선택 또는 생성"""
        try:
            chatrooms = self.get_chatrooms()
            
            if not chatrooms:
                print("기존 채팅방이 없습니다. 새로운 채팅방을 생성합니다...")
                new_room_id = self.create_chatroom()
                self.current_chatroom_id = new_room_id
                print(f"새 채팅방 {new_room_id}번이 생성되었습니다.")
                return new_room_id
            
            print("\n=== 기존 채팅방 목록 ===")
            for room in chatrooms:
                print(f"방 {room['id']}번: 메시지 {room['message_count']}개, "
                      f"마지막 활동: {room['last_activity'] or '없음'}")
            
            user_input = self.get_user_input_with_timeout(
                '\n어느 채팅방에 들어가시겠습니까? (숫자 입력, 새 방 생성은 "new" 입력): '
            )
            
            if user_input is None:
                # 타임아웃 - 새 방 생성
                new_room_id = self.create_chatroom()
                self.current_chatroom_id = new_room_id
                print(f"새 채팅방 {new_room_id}번이 생성되었습니다.")
                return new_room_id
            
            if user_input.lower() == 'new':
                new_room_id = self.create_chatroom()
                self.current_chatroom_id = new_room_id
                print(f"새 채팅방 {new_room_id}번이 생성되었습니다.")
                return new_room_id
            
            try:
                selected_room_id = int(user_input)
                room_exists = any(room['id'] == selected_room_id for room in chatrooms)
                
                if room_exists:
                    self.current_chatroom_id = selected_room_id
                    print(f"채팅방 {selected_room_id}번에 입장했습니다.")
                    return selected_room_id
                else:
                    print("존재하지 않는 채팅방입니다. 새로운 채팅방을 생성합니다...")
                    new_room_id = self.create_chatroom()
                    self.current_chatroom_id = new_room_id
                    print(f"새 채팅방 {new_room_id}번이 생성되었습니다.")
                    return new_room_id
            except ValueError:
                print("잘못된 입력입니다. 새로운 채팅방을 생성합니다...")
                new_room_id = self.create_chatroom()
                self.current_chatroom_id = new_room_id
                print(f"새 채팅방 {new_room_id}번이 생성되었습니다.")
                return new_room_id
                
        except Exception as error:
            print(f"채팅방 선택 중 오류: {error}")
            raise error
    
    def get_chatroom_history(self, chatroom_id, limit=100, offset=0):
        """특정 채팅방의 대화 내역 가져오기"""
        cursor = self.connection.cursor()
        
        # 채팅 메시지와 응답을 시간순으로 정렬해서 가져오기
        cursor.execute("""
            SELECT 
                c.id as chat_id,
                c.message as user_message,
                c.created_at as chat_time,
                r.id as response_id,
                r.message as bot_response,
                r.created_at as response_time
            FROM chat c
            LEFT JOIN response r ON c.id = r.chat_id
            WHERE c.chatroom_id = ?
            ORDER BY c.created_at ASC, r.created_at ASC
            LIMIT ? OFFSET ?
        """, (chatroom_id, limit, offset))
        
        return cursor.fetchall()
    
    def get_chatroom_message_count(self, chatroom_id):
        """특정 채팅방의 총 메시지 수 조회"""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total_messages
            FROM chat 
            WHERE chatroom_id = ?
        """, (chatroom_id,))
        
        result = cursor.fetchone()
        return result['total_messages'] if result else 0
    
    def get_recent_messages(self, chatroom_id, limit=10):
        """최근 메시지들만 간단히 가져오기"""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT 
                c.id as chat_id,
                c.message as user_message,
                c.created_at as chat_time,
                r.message as bot_response,
                r.created_at as response_time
            FROM chat c
            LEFT JOIN response r ON c.id = r.chat_id
            WHERE c.chatroom_id = ?
            ORDER BY c.created_at DESC
            LIMIT ?
        """, (chatroom_id, limit))
        
        results = cursor.fetchall()
        return list(reversed(results))  # 시간순으로 다시 정렬
    
    def get_all_chatroom_data(self, chatroom_id):
        """특정 채팅방의 모든 Chat과 Response 데이터를 구조화해서 가져오기"""
        cursor = self.connection.cursor()
        
        # 모든 채팅 메시지 가져오기
        cursor.execute("""
            SELECT id, message, created_at
            FROM chat 
            WHERE chatroom_id = ?
            ORDER BY created_at ASC
        """, (chatroom_id,))
        
        chats = cursor.fetchall()
        
        # 각 채팅에 대한 응답들 가져오기
        result = []
        for chat in chats:
            chat_id = chat['id']
            
            # 해당 채팅의 모든 응답 가져오기 (이미지 경로 포함)
            cursor.execute("""
                SELECT id, message, image_path, created_at
                FROM response 
                WHERE chat_id = ?
                ORDER BY created_at ASC
            """, (chat_id,))
            
            responses = cursor.fetchall()
            
            # 채팅과 응답을 함께 구조화
            chat_data = {
                "chat": {
                    "id": chat['id'],
                    "message": chat['message'],
                    "created_at": chat['created_at']
                },
                "responses": [
                    {
                        "id": response['id'],
                        "message": response['message'],
                        "image_path": response['image_path'],
                        "created_at": response['created_at']
                    }
                    for response in responses
                ]
            }
            
            result.append(chat_data)
        
        return result
    
    def get_chatroom_timeline(self, chatroom_id):
        """채팅방의 모든 메시지를 시간순으로 정렬한 타임라인"""
        cursor = self.connection.cursor()
        
        # Chat과 Response를 모두 시간순으로 가져오기 (이미지 경로 포함)
        cursor.execute("""
            SELECT 
                'chat' as type,
                c.id as id,
                c.message as message,
                c.created_at as created_at,
                c.id as chat_id,
                NULL as response_to_chat_id,
                NULL as image_path
            FROM chat c
            WHERE c.chatroom_id = ?
            
            UNION ALL
            
            SELECT 
                'response' as type,
                r.id as id,
                r.message as message,
                r.created_at as created_at,
                r.chat_id as chat_id,
                r.chat_id as response_to_chat_id,
                r.image_path as image_path
            FROM response r
            JOIN chat c ON r.chat_id = c.id
            WHERE c.chatroom_id = ?
            
            ORDER BY created_at ASC
        """, (chatroom_id, chatroom_id))
        
        return cursor.fetchall()
    
    def close(self):
        """데이터베이스 연결 종료"""
        if self.connection:
            self.connection.close()
            print("데이터베이스 연결이 종료되었습니다.")

# 전역 데이터베이스 인스턴스
chat_db = None

async def initialize_chat_system():
    """채팅 시스템 초기화 (비동기)"""
    global chat_db
    
    def run_initialization():
        global chat_db
        chat_db = ChatDatabase()
        
        try:
            print("=== 채팅 시스템 초기화 ===")
            db_existed = chat_db.initialize_database()
            
            # 채팅방 선택은 별도 스레드에서 실행 (FastAPI 시작을 블로킹하지 않음)
            chatroom_id = chat_db.select_or_create_chatroom()
            print(f"채팅 시스템이 준비되었습니다! (채팅방: {chatroom_id}번)")
            print("=" * 40)
            
        except Exception as error:
            print(f"채팅 시스템 초기화 오류: {error}")
            if chat_db:
                chat_db.close()
    
    # 별도 스레드에서 초기화 실행 (콘솔 입력이 있으므로)
    thread = threading.Thread(target=run_initialization)
    thread.daemon = True
    thread.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 실행
    await initialize_chat_system()
    yield
    # 종료 시 실행
    global chat_db
    if chat_db:
        chat_db.close()

# FastAPI 앱 생성 (lifespan 사용)
app = FastAPI(
    title="Chat API with SQLite",
    description="SQLite를 사용한 채팅 API",
    version="1.0.0",
    lifespan=lifespan
)

# API 엔드포인트들
@app.get("/")
async def root():
    return {"message": "Chat API with SQLite is running!"}

@app.get("/chatrooms")
async def get_chatrooms():
    """채팅방 목록 조회"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        chatrooms = chat_db.get_chatrooms()
        return {"chatrooms": [dict(room) for room in chatrooms]}
    except Exception as e:
        return {"error": str(e)}

@app.post("/chatrooms")
async def create_chatroom():
    """새 채팅방 생성"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        room_id = chat_db.create_chatroom()
        return {"chatroom_id": room_id, "message": f"채팅방 {room_id}번이 생성되었습니다."}
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat")
async def send_message(message: str, chatroom_id: int = None):
    """메시지 전송"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    # 현재 채팅방 ID 사용 (파라미터로 전달되지 않은 경우)
    if chatroom_id is None:
        chatroom_id = chat_db.current_chatroom_id
    
    if chatroom_id is None:
        return {"error": "No active chatroom"}
    
    try:
        # 메시지 저장
        chat_id = chat_db.save_message(message, chatroom_id)
        
        # 간단한 응답 생성 (실제로는 AI 로직 등을 사용)
        response_message = f"응답: {message}에 대한 답변입니다."
        response_id = chat_db.save_response(response_message, chat_id)
        
        return {
            "chat_id": chat_id,
            "response_id": response_id,
            "response": response_message,
            "chatroom_id": chatroom_id,
            "image_path": None
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat-with-image")
async def send_message_with_image(
    message: str, 
    original_image_filename: str,
    module_name: str,
    chatroom_id: int = None
):
    """메시지와 이미지를 함께 전송"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    # 현재 채팅방 ID 사용 (파라미터로 전달되지 않은 경우)
    if chatroom_id is None:
        chatroom_id = chat_db.current_chatroom_id
    
    if chatroom_id is None:
        return {"error": "No active chatroom"}
    
    try:
        # 메시지 저장
        chat_id = chat_db.save_message(message, chatroom_id)
        
        # 간단한 응답 생성 (실제로는 AI 로직 등을 사용)
        response_message = f"응답: {message}에 대한 답변입니다. (이미지 포함)"
        
        # 응답과 이미지를 함께 저장
        result = chat_db.save_response_with_image(
            response_message, 
            chat_id, 
            chatroom_id, 
            original_image_filename, 
            module_name
        )
        
        if result["success"]:
            return {
                "chat_id": chat_id,
                "response_id": result["response_id"],
                "response": response_message,
                "chatroom_id": chatroom_id,
                "image_path": result["image_path"],
                "success": True
            }
        else:
            return {
                "error": f"Image processing failed: {result.get('error', 'Unknown error')}",
                "chat_id": chat_id,
                "success": False
            }
        
    except Exception as e:
        return {"error": str(e)}

@app.post("/process-existing-image")
async def process_existing_image(
    response_id: int,
    original_image_filename: str,
    module_name: str,
    chatroom_id: int
):
    """기존 응답에 이미지 추가 (이미 생성된 이미지를 처리)"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        # 이미지 이동 및 이름 변경
        image_path = chat_db.move_and_rename_image(
            original_image_filename, 
            chatroom_id, 
            module_name
        )
        
        if image_path:
            # 기존 응답에 이미지 경로 업데이트
            cursor = chat_db.connection.cursor()
            cursor.execute(
                'UPDATE response SET image_path = ? WHERE id = ?',
                (image_path, response_id)
            )
            chat_db.connection.commit()
            
            return {
                "success": True,
                "response_id": response_id,
                "image_path": image_path,
                "message": "이미지가 성공적으로 처리되었습니다."
            }
        else:
            return {
                "success": False,
                "error": "이미지 처리에 실패했습니다."
            }
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/current-chatroom")
async def get_current_chatroom():
    """현재 활성 채팅방 조회"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    return {"current_chatroom_id": chat_db.current_chatroom_id}

@app.get("/chatrooms/{chatroom_id}/history")
async def get_chatroom_history(
    chatroom_id: int, 
    limit: int = 100, 
    offset: int = 0
):
    """특정 채팅방의 대화 내역 조회 (페이지네이션 지원)"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        # 대화 내역 가져오기
        history = chat_db.get_chatroom_history(chatroom_id, limit, offset)
        total_messages = chat_db.get_chatroom_message_count(chatroom_id)
        
        # 결과를 더 읽기 쉬운 형태로 변환
        conversations = []
        for row in history:
            conversation = {
                "chat_id": row["chat_id"],
                "user_message": row["user_message"],
                "chat_time": row["chat_time"],
                "bot_response": row["bot_response"],
                "response_time": row["response_time"],
                "response_id": row["response_id"]
            }
            conversations.append(conversation)
        
        return {
            "chatroom_id": chatroom_id,
            "conversations": conversations,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_messages": total_messages,
                "has_more": offset + limit < total_messages
            }
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/chatrooms/{chatroom_id}/messages")
async def get_recent_messages(chatroom_id: int, limit: int = 10):
    """특정 채팅방의 최근 메시지들 조회"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        messages = chat_db.get_recent_messages(chatroom_id, limit)
        
        # 결과를 더 읽기 쉬운 형태로 변환
        conversations = []
        for row in messages:
            conversation = {
                "chat_id": row["chat_id"],
                "user_message": row["user_message"],
                "chat_time": row["chat_time"],
                "bot_response": row["bot_response"],
                "response_time": row["response_time"]
            }
            conversations.append(conversation)
        
        return {
            "chatroom_id": chatroom_id,
            "recent_conversations": conversations,
            "count": len(conversations)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/chatrooms/{chatroom_id}/info")
async def get_chatroom_info(chatroom_id: int):
    """특정 채팅방 정보 조회"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        # 채팅방 존재 여부 확인
        chatrooms = chat_db.get_chatrooms()
        chatroom_exists = any(room['id'] == chatroom_id for room in chatrooms)
        
        if not chatroom_exists:
            return {"error": "Chatroom not found"}
        
        # 메시지 수 조회
        total_messages = chat_db.get_chatroom_message_count(chatroom_id)
        
        # 최근 활동 시간 조회
        cursor = chat_db.connection.cursor()
        cursor.execute("""
            SELECT MAX(created_at) as last_activity
            FROM chat 
            WHERE chatroom_id = ?
        """, (chatroom_id,))
        
        result = cursor.fetchone()
        last_activity = result['last_activity'] if result else None
        
        return {
            "chatroom_id": chatroom_id,
            "total_messages": total_messages,
            "last_activity": last_activity,
            "exists": True
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/chatrooms/{chatroom_id}/all-data")
async def get_all_chatroom_data(chatroom_id: int):
    """특정 채팅방의 모든 Chat과 Response를 구조화해서 조회"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        # 채팅방 존재 여부 확인
        chatrooms = chat_db.get_chatrooms()
        chatroom_exists = any(room['id'] == chatroom_id for room in chatrooms)
        
        if not chatroom_exists:
            return {"error": "Chatroom not found"}
        
        # 모든 채팅 데이터 가져오기
        all_data = chat_db.get_all_chatroom_data(chatroom_id)
        
        # 통계 정보 계산
        total_chats = len(all_data)
        total_responses = sum(len(item['responses']) for item in all_data)
        
        return {
            "chatroom_id": chatroom_id,
            "total_chats": total_chats,
            "total_responses": total_responses,
            "conversations": all_data
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/chatrooms/{chatroom_id}/timeline")
async def get_chatroom_timeline(chatroom_id: int):
    """특정 채팅방의 모든 메시지를 시간순 타임라인으로 조회"""
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        # 채팅방 존재 여부 확인
        chatrooms = chat_db.get_chatrooms()
        chatroom_exists = any(room['id'] == chatroom_id for room in chatrooms)
        
        if not chatroom_exists:
            return {"error": "Chatroom not found"}
        
        # 타임라인 데이터 가져오기
        timeline = chat_db.get_chatroom_timeline(chatroom_id)
        
        # 결과를 더 읽기 쉬운 형태로 변환
        messages = []
        for row in timeline:
            message = {
                "type": row["type"],  # 'chat' or 'response'
                "id": row["id"],
                "message": row["message"],
                "created_at": row["created_at"],
                "chat_id": row["chat_id"],  # 어떤 채팅의 응답인지 알 수 있음
                "is_response_to_chat": row["response_to_chat_id"],  # response인 경우 어떤 chat에 대한 응답인지
                "image_path": row["image_path"]  # 이미지 경로 (response인 경우에만)
            }
            messages.append(message)
        
        return {
            "chatroom_id": chatroom_id,
            "total_messages": len(messages),
            "timeline": messages
        }
    except Exception as e:
        return {"error": str(e)}

# 예시: 기존 FastAPI 코드와 통합하는 방법
"""
기존 main.py가 있다면 다음과 같이 통합하세요:

1. 위의 ChatDatabase 클래스와 initialize_chat_system 함수를 복사
2. lifespan 함수를 기존 앱에 추가하거나 기존 startup event에 통합
3. 필요한 API 엔드포인트들을 추가

예시:
from fastapi import FastAPI

# 기존 코드...

app = FastAPI(lifespan=lifespan)  # lifespan 추가

# 또는 기존 방식 사용:
@app.on_event("startup")
async def startup_event():
    await initialize_chat_system()
    # 기존 startup 코드...

@app.on_event("shutdown") 
async def shutdown_event():
    global chat_db
    if chat_db:
        chat_db.close()
    # 기존 shutdown 코드...
"""

if __name__ == "__main__":
    import uvicorn
    
    # Graceful shutdown 처리
    def signal_handler(signum, frame):
        global chat_db
        if chat_db:
            chat_db.close()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
