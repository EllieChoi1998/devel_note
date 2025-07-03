const sqlite3 = require('sqlite3').verbose();
const readline = require('readline');
const fs = require('fs');
const path = require('path');

class ChatDatabase {
    constructor() {
        this.dbPath = './sqlite.db';
        this.db = null;
        this.currentChatroomId = null;
    }

    // 데이터베이스 초기화
    async initializeDatabase() {
        return new Promise((resolve, reject) => {
            const dbExists = fs.existsSync(this.dbPath);
            
            this.db = new sqlite3.Database(this.dbPath, (err) => {
                if (err) {
                    console.error('데이터베이스 연결 오류:', err.message);
                    reject(err);
                    return;
                }
                
                if (!dbExists) {
                    console.log('새로운 SQLite 데이터베이스를 생성합니다...');
                    this.createTables()
                        .then(() => resolve(false)) // 새 DB
                        .catch(reject);
                } else {
                    console.log('기존 SQLite 데이터베이스를 발견했습니다.');
                    resolve(true); // 기존 DB
                }
            });
        });
    }

    // 테이블 생성
    createTables() {
        return new Promise((resolve, reject) => {
            const queries = [
                `CREATE TABLE chatroom (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )`,
                `CREATE TABLE chat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    chatroom_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chatroom_id) REFERENCES chatroom(id)
                )`,
                `CREATE TABLE response (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    chat_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES chat(id)
                )`
            ];

            this.db.serialize(() => {
                queries.forEach((query, index) => {
                    this.db.run(query, (err) => {
                        if (err) {
                            console.error(`테이블 생성 오류 (${index + 1}):`, err.message);
                            reject(err);
                            return;
                        }
                        if (index === queries.length - 1) {
                            console.log('모든 테이블이 생성되었습니다.');
                            resolve();
                        }
                    });
                });
            });
        });
    }

    // 채팅방 리스트 가져오기
    getChatrooms() {
        return new Promise((resolve, reject) => {
            this.db.all(`
                SELECT c.id, COUNT(ch.id) as message_count, 
                       MAX(ch.created_at) as last_activity
                FROM chatroom c
                LEFT JOIN chat ch ON c.id = ch.chatroom_id
                GROUP BY c.id
                ORDER BY last_activity DESC
            `, (err, rows) => {
                if (err) {
                    reject(err);
                } else {
                    resolve(rows);
                }
            });
        });
    }

    // 새 채팅방 생성
    createChatroom() {
        return new Promise((resolve, reject) => {
            this.db.run('INSERT INTO chatroom DEFAULT VALUES', function(err) {
                if (err) {
                    reject(err);
                } else {
                    resolve(this.lastID);
                }
            });
        });
    }

    // 메시지 저장
    saveMessage(message, chatroomId) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'INSERT INTO chat (message, chatroom_id) VALUES (?, ?)',
                [message, chatroomId],
                function(err) {
                    if (err) {
                        reject(err);
                    } else {
                        resolve(this.lastID);
                    }
                }
            );
        });
    }

    // 응답 저장
    saveResponse(responseMessage, chatId) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'INSERT INTO response (message, chat_id) VALUES (?, ?)',
                [responseMessage, chatId],
                function(err) {
                    if (err) {
                        reject(err);
                    } else {
                        resolve(this.lastID);
                    }
                }
            );
        });
    }

    // 30초 타임아웃으로 사용자 입력 받기
    getUserInputWithTimeout(question, timeoutMs = 30000) {
        return new Promise((resolve) => {
            const rl = readline.createInterface({
                input: process.stdin,
                output: process.stdout
            });

            let answered = false;
            
            // 타임아웃 설정
            const timeout = setTimeout(() => {
                if (!answered) {
                    answered = true;
                    rl.close();
                    console.log('\n시간 초과! 새로운 채팅방을 생성합니다...');
                    resolve(null);
                }
            }, timeoutMs);

            rl.question(question, (answer) => {
                if (!answered) {
                    answered = true;
                    clearTimeout(timeout);
                    rl.close();
                    resolve(answer.trim());
                }
            });
        });
    }

    // 채팅방 선택 또는 생성
    async selectOrCreateChatroom() {
        try {
            const chatrooms = await this.getChatrooms();
            
            if (chatrooms.length === 0) {
                console.log('기존 채팅방이 없습니다. 새로운 채팅방을 생성합니다...');
                const newRoomId = await this.createChatroom();
                this.currentChatroomId = newRoomId;
                console.log(`새 채팅방 ${newRoomId}번이 생성되었습니다.`);
                return newRoomId;
            }

            console.log('\n=== 기존 채팅방 목록 ===');
            chatrooms.forEach(room => {
                console.log(`방 ${room.id}번: 메시지 ${room.message_count}개, 마지막 활동: ${room.last_activity || '없음'}`);
            });

            const userInput = await this.getUserInputWithTimeout(
                '\n어느 채팅방에 들어가시겠습니까? (숫자 입력, 새 방 생성은 "new" 입력): '
            );

            if (userInput === null) {
                // 타임아웃 - 새 방 생성
                const newRoomId = await this.createChatroom();
                this.currentChatroomId = newRoomId;
                console.log(`새 채팅방 ${newRoomId}번이 생성되었습니다.`);
                return newRoomId;
            }

            if (userInput.toLowerCase() === 'new') {
                const newRoomId = await this.createChatroom();
                this.currentChatroomId = newRoomId;
                console.log(`새 채팅방 ${newRoomId}번이 생성되었습니다.`);
                return newRoomId;
            }

            const selectedRoomId = parseInt(userInput);
            const roomExists = chatrooms.some(room => room.id === selectedRoomId);
            
            if (roomExists) {
                this.currentChatroomId = selectedRoomId;
                console.log(`채팅방 ${selectedRoomId}번에 입장했습니다.`);
                return selectedRoomId;
            } else {
                console.log('존재하지 않는 채팅방입니다. 새로운 채팅방을 생성합니다...');
                const newRoomId = await this.createChatroom();
                this.currentChatroomId = newRoomId;
                console.log(`새 채팅방 ${newRoomId}번이 생성되었습니다.`);
                return newRoomId;
            }
        } catch (error) {
            console.error('채팅방 선택 중 오류:', error);
            throw error;
        }
    }

    // 데이터베이스 연결 종료
    close() {
        if (this.db) {
            this.db.close((err) => {
                if (err) {
                    console.error('데이터베이스 종료 오류:', err.message);
                } else {
                    console.log('데이터베이스 연결이 종료되었습니다.');
                }
            });
        }
    }
}

// 사용 예시
async function startChatApplication() {
    const chatDB = new ChatDatabase();
    
    try {
        // 데이터베이스 초기화
        const dbExisted = await chatDB.initializeDatabase();
        
        // 채팅방 선택 또는 생성
        const chatroomId = await chatDB.selectOrCreateChatroom();
        
        console.log(`\n채팅을 시작합니다! (채팅방: ${chatroomId}번)`);
        console.log('메시지를 입력하세요. 종료하려면 "exit"을 입력하세요.\n');
        
        // 간단한 채팅 루프
        const rl = readline.createInterface({
            input: process.stdin,
            output: process.stdout
        });

        const chatLoop = () => {
            rl.question('메시지: ', async (message) => {
                if (message.toLowerCase() === 'exit') {
                    rl.close();
                    chatDB.close();
                    return;
                }

                try {
                    // 메시지 저장
                    const chatId = await chatDB.saveMessage(message, chatroomId);
                    console.log(`메시지가 저장되었습니다. (ID: ${chatId})`);
                    
                    // 간단한 응답 생성 (실제로는 AI나 다른 로직 사용)
                    const responseMessage = `응답: ${message}에 대한 답변입니다.`;
                    const responseId = await chatDB.saveResponse(responseMessage, chatId);
                    console.log(`응답: ${responseMessage} (ID: ${responseId})\n`);
                    
                } catch (error) {
                    console.error('메시지 처리 중 오류:', error);
                }
                
                chatLoop();
            });
        };

        chatLoop();
        
    } catch (error) {
        console.error('애플리케이션 시작 오류:', error);
        chatDB.close();
    }
}

// 애플리케이션 시작
if (require.main === module) {
    startChatApplication();
}

module.exports = ChatDatabase;