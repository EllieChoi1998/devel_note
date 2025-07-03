# main.py
import sqlite3
import threading
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI

# ChatDatabase 클래스 (위에서 작성한 것과 동일)
class ChatDatabase:
    def __init__(self):
        self.db_path = './sqlite.db'
        self.current_chatroom_id = None
        self.connection = None
    
    def initialize_database(self):
        db_exists = os.path.exists(self.db_path)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        
        if not db_exists:
            print("새로운 SQLite 데이터베이스를 생성합니다...")
            self.create_tables()
            return False
        else:
            print("기존 SQLite 데이터베이스를 발견했습니다.")
            return True
    
    def create_tables(self):
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chat(id)
            )"""
        ]
        
        for query in queries:
            cursor.execute(query)
        self.connection.commit()
        print("모든 테이블이 생성되었습니다.")
    
    def get_chatrooms(self):
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
        cursor = self.connection.cursor()
        cursor.execute('INSERT INTO chatroom DEFAULT VALUES')
        self.connection.commit()
        return cursor.lastrowid
    
    def save_message(self, message, chatroom_id):
        cursor = self.connection.cursor()
        cursor.execute(
            'INSERT INTO chat (message, chatroom_id) VALUES (?, ?)',
            (message, chatroom_id)
        )
        self.connection.commit()
        return cursor.lastrowid
    
    def save_response(self, response_message, chat_id):
        cursor = self.connection.cursor()
        cursor.execute(
            'INSERT INTO response (message, chat_id) VALUES (?, ?)',
            (response_message, chat_id)
        )
        self.connection.commit()
        return cursor.lastrowid
    
    def get_user_input_with_timeout(self, question, timeout_seconds=30):
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
    
    def close(self):
        if self.connection:
            self.connection.close()
            print("데이터베이스 연결이 종료되었습니다.")

# 전역 데이터베이스 인스턴스
chat_db = None

async def initialize_chat_system():
    """채팅 시스템 초기화"""
    global chat_db
    
    def run_initialization():
        global chat_db
        chat_db = ChatDatabase()
        
        try:
            print("=== 채팅 시스템 초기화 ===")
            db_existed = chat_db.initialize_database()
            chatroom_id = chat_db.select_or_create_chatroom()
            print(f"채팅 시스템이 준비되었습니다! (채팅방: {chatroom_id}번)")
            print("=" * 40)
            
        except Exception as error:
            print(f"채팅 시스템 초기화 오류: {error}")
            if chat_db:
                chat_db.close()
    
    thread = threading.Thread(target=run_initialization)
    thread.daemon = True
    thread.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 실행
    await initialize_chat_system()
    yield
    # 앱 종료 시 실행
    global chat_db
    if chat_db:
        chat_db.close()

# FastAPI 앱 생성 (기존 앱에 lifespan 추가)
app = FastAPI(lifespan=lifespan)

# 기존 엔드포인트들...
@app.get("/")
async def root():
    return {"message": "Hello World with SQLite Chat!"}

# 채팅 관련 새 엔드포인트들
@app.get("/chatrooms")
async def get_chatrooms():
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    try:
        chatrooms = chat_db.get_chatrooms()
        return {"chatrooms": [dict(room) for room in chatrooms]}
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat")
async def send_message(message: str, chatroom_id: int = None):
    global chat_db
    if not chat_db:
        return {"error": "Database not initialized"}
    
    if chatroom_id is None:
        chatroom_id = chat_db.current_chatroom_id
    
    if chatroom_id is None:
        return {"error": "No active chatroom"}
    
    try:
        chat_id = chat_db.save_message(message, chatroom_id)
        response_message = f"응답: {message}에 대한 답변입니다."
        response_id = chat_db.save_response(response_message, chat_id)
        
        return {
            "chat_id": chat_id,
            "response_id": response_id,
            "response": response_message,
            "chatroom_id": chatroom_id
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)