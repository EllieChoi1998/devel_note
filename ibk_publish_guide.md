# IBK 시스템 배포 절차 (인코딩 문제 수정 포함)

## 📌 사전 준비사항

- 작업 디렉토리에 모든 파일 확인
- Docker 및 Docker Compose 설치 확인
- 충분한 디스크 공간 확인 (최소 20GB 권장)

---

## 0️⃣ 분할 조각 합치기

```bash
# 프론트엔드
[ -f ibk-frontend_2025-10-21.tar.gz.part-aa ] && \
cat ibk-frontend_2025-10-21.tar.gz.part-* > ibk-frontend_2025-10-21.tar.gz

# 백엔드
[ -f ibk-backend_2025-10-21.tar.gz.part-aa ] && \
cat ibk-backend_2025-10-21.tar.gz.part-* > ibk-backend_2025-10-21.tar.gz

# MySQL
[ -f ibk-mysql_8.0-custom.tar.gz.part-aa ] && \
cat ibk-mysql_8.0-custom.tar.gz.part-* > ibk-mysql_8.0-custom.tar.gz

# 합친 파일 확인
ls -lh ibk-*.tar.gz
```

---

## 1️⃣ Docker 이미지 로드

```bash
# 이미지 로드
gunzip -c ibk-frontend_2025-10-21.tar.gz | docker load
gunzip -c ibk-backend_2025-10-21.tar.gz  | docker load
gunzip -c ibk-mysql_8.0-custom.tar.gz    | docker load

# 로드된 이미지 확인
docker images | grep -E 'ibk-|mysql'

# ⚠️ 출력된 IMAGE ID와 TAG를 기록해두세요
# 예상 결과:
# ibk-frontend:2025-10-21
# ibk-backend:2025-10-21
# ibk-mysql:8.0-custom (또는 mysql:8.0)
```

---

## 🔧 2️⃣ **인코딩 문제 수정 (핵심 단계)**

### 2-1. 프론트엔드 인코딩 수정

```bash
# iconv 설치 확인 (없으면 설치)
which iconv || yum install -y glibc-common  # RHEL/CentOS
# which iconv || apt-get install -y libc-bin  # Debian/Ubuntu

# 임시 작업 디렉토리 생성
mkdir -p /tmp/frontend-fix

# 프론트엔드 소스코드 추출 및 인코딩 변환
docker run --rm -v /tmp/frontend-fix:/workspace ibk-frontend:2025-10-21 sh -c '
  if [ -d /app ]; then
    cp -r /app /workspace/
  elif [ -d /usr/share/nginx/html ]; then
    cp -r /usr/share/nginx/html /workspace/app
  fi
'

# Latin-1 → UTF-8 변환
find /tmp/frontend-fix/app -type f \( \
  -name "*.js" -o -name "*.html" -o -name "*.css" -o \
  -name "*.json" -o -name "*.vue" -o -name "*.jsx" -o \
  -name "*.tsx" -o -name "*.ts" \
\) -exec sh -c '
  if file "$1" | grep -q "text"; then
    iconv -f LATIN1 -t UTF-8 "$1" -o "$1.tmp" 2>/dev/null && mv "$1.tmp" "$1" || true
  fi
' _ {} \;

# 수정된 이미지 생성
cat > /tmp/Dockerfile.frontend.fix << 'FRONTEND_EOF'
FROM ibk-frontend:2025-10-21
COPY app /app
FRONTEND_EOF

cd /tmp/frontend-fix
docker build -f /tmp/Dockerfile.frontend.fix -t ibk-frontend:fixed .
docker tag ibk-frontend:fixed ibk-frontend:latest
cd -

echo "✅ 프론트엔드 인코딩 수정 완료"
```

### 2-2. 백엔드 인코딩 수정

```bash
# 임시 작업 디렉토리 생성
mkdir -p /tmp/backend-fix

# 백엔드 소스코드 추출
docker run --rm -v /tmp/backend-fix:/workspace ibk-backend:2025-10-21 sh -c '
  if [ -d /app ]; then
    cp -r /app /workspace/
  fi
'

# Latin-1 → UTF-8 변환
find /tmp/backend-fix/app -type f \( \
  -name "*.py" -o -name "*.js" -o -name "*.json" -o \
  -name "*.sql" -o -name "*.txt" -o -name "*.md" \
\) -exec sh -c '
  if file "$1" | grep -q "text"; then
    iconv -f LATIN1 -t UTF-8 "$1" -o "$1.tmp" 2>/dev/null && mv "$1.tmp" "$1" || true
  fi
' _ {} \;

# 수정된 이미지 생성
cat > /tmp/Dockerfile.backend.fix << 'BACKEND_EOF'
FROM ibk-backend:2025-10-21
COPY app /app
BACKEND_EOF

cd /tmp/backend-fix
docker build -f /tmp/Dockerfile.backend.fix -t ibk-backend:fixed .
docker tag ibk-backend:fixed ibk-backend:latest
cd -

echo "✅ 백엔드 인코딩 수정 완료"
```

### 2-3. docker-compose.yml 인코딩 수정

```bash
# 현재 인코딩 확인
file -i docker-compose.yml

# UTF-8이 아니면 변환
if ! file -i docker-compose.yml | grep -q "utf-8"; then
  iconv -f LATIN1 -t UTF-8 docker-compose.yml -o docker-compose.yml.utf8
  mv docker-compose.yml.utf8 docker-compose.yml
  echo "✅ docker-compose.yml 인코딩 변환 완료"
else
  echo "✅ docker-compose.yml 이미 UTF-8"
fi
```

---

## 3️⃣ MySQL 이미지 태그 정리

```bash
# MySQL 이미지 latest 태그 추가
# (로드된 이미지명에 맞게 선택)

# 경우 1: ibk-mysql:8.0-custom 으로 로드된 경우
docker tag ibk-mysql:8.0-custom mysql:latest

# 경우 2: mysql:8.0 으로 로드된 경우
docker tag mysql:8.0 mysql:latest

# 태그 확인
docker images | grep mysql
```

---

## 🔧 4️⃣ **MySQL 데이터 인코딩 수정 및 복원**

```bash
# 볼륨 생성
docker volume create ibk_mysql_data

# 임시 디렉토리에 데이터 추출
mkdir -p /tmp/mysql-fix
tar -xf ibk_mysql_data.tar -C /tmp/mysql-fix

# SQL 파일 인코딩 변환
echo "🔄 MySQL 데이터 인코딩 변환 중..."
find /tmp/mysql-fix -type f -exec sh -c '
  if file "$1" | grep -q "text"; then
    iconv -f LATIN1 -t UTF-8 "$1" -o "$1.tmp" 2>/dev/null && mv "$1.tmp" "$1" || true
  fi
' _ {} \;

# 수정된 데이터로 새 tar 생성
cd /tmp/mysql-fix
tar -cf /tmp/ibk_mysql_data_fixed.tar .
cd -

# 수정된 tar로 볼륨 복원
docker run --rm \
  -v ibk_mysql_data:/to \
  -v /tmp:/from \
  mysql:latest sh -c 'cd /to && tar -xf /from/ibk_mysql_data_fixed.tar'

# 복원 확인
docker run --rm -v ibk_mysql_data:/check mysql:latest sh -c 'ls -la /check | head -20'

echo "✅ MySQL 데이터 인코딩 수정 및 복원 완료"
```

---

## 5️⃣ 서비스 실행

```bash
# 기존 컨테이너 정리 (있는 경우)
docker compose down 2>/dev/null || true

# 서비스 시작
docker compose up -d

# 상태 확인
docker compose ps

# 로그 확인
docker compose logs -f
```

---

## 6️⃣ 최종 확인

### MySQL 연결 테스트

```bash
# MySQL 컨테이너 접속
docker exec -it ibk_mysql mysql -uroot -proot

docker exec -it ibk_mysql mysql -uroot -proot mydb --default-character-set=utf8mb4 -e "
SELECT id, question FROM checklist LIMIT 3;
"

# MySQL 쉘에서 실행:
# SHOW DATABASES;
# USE your_database;
# SELECT * FROM your_table LIMIT 5;
# \q
```

# 위까지 다 했는데 문제생기면
# 1. content_temp 컬럼이 있는지 확인하고 삭제
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
SET @exist := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_SCHEMA = 'mydb' 
               AND TABLE_NAME = 'checklist' 
               AND COLUMN_NAME = 'content_temp');
SET @sqlstmt := IF(@exist > 0, 'ALTER TABLE checklist DROP COLUMN content_temp', 'SELECT 1');
PREPARE stmt FROM @sqlstmt;
EXECUTE stmt;
"

# 2. question 컬럼 수정
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
ALTER TABLE checklist ADD COLUMN question_temp VARCHAR(512) CHARACTER SET utf8mb4;
UPDATE checklist SET question_temp = CONVERT(CAST(CONVERT(question USING latin1) AS BINARY) USING utf8mb4);
UPDATE checklist SET question = question_temp;
ALTER TABLE checklist DROP COLUMN question_temp;
"

# 3. prompt_msg 컬럼 수정
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
ALTER TABLE checklist ADD COLUMN prompt_msg_temp VARCHAR(2000) CHARACTER SET utf8mb4;
UPDATE checklist SET prompt_msg_temp = CONVERT(CAST(CONVERT(prompt_msg USING latin1) AS BINARY) USING utf8mb4);
UPDATE checklist SET prompt_msg = prompt_msg_temp;
ALTER TABLE checklist DROP COLUMN prompt_msg_temp;
"

# 4. 결과 확인
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
SELECT id, question FROM checklist LIMIT 3;
"

# content_temp 삭제 시도 (에러 나도 계속 진행)
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
ALTER TABLE checklist DROP COLUMN content_temp;
" 2>/dev/null || echo "content_temp 컬럼 없음 (정상)"

# question 컬럼 수정
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
ALTER TABLE checklist ADD COLUMN question_temp VARCHAR(512) CHARACTER SET utf8mb4;
UPDATE checklist SET question_temp = CONVERT(CAST(CONVERT(question USING latin1) AS BINARY) USING utf8mb4);
UPDATE checklist SET question = question_temp;
ALTER TABLE checklist DROP COLUMN question_temp;
"

echo "✅ question 컬럼 수정 완료"

# prompt_msg 컬럼 수정
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
ALTER TABLE checklist ADD COLUMN prompt_msg_temp VARCHAR(2000) CHARACTER SET utf8mb4;
UPDATE checklist SET prompt_msg_temp = CONVERT(CAST(CONVERT(prompt_msg USING latin1) AS BINARY) USING utf8mb4);
UPDATE checklist SET prompt_msg = prompt_msg_temp;
ALTER TABLE checklist DROP COLUMN prompt_msg_temp;
"

echo "✅ prompt_msg 컬럼 수정 완료"

# 결과 확인
echo ""
echo "=== 결과 확인 ==="
docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
SELECT id, LEFT(question, 80) AS question_preview FROM checklist LIMIT 3;
"


docker exec -it ibk_mysql mysql -uroot -proot mydb -e "
SELECT id, HEX(LEFT(question, 20)) as hex_value FROM checklist LIMIT 1;
"



### 백엔드 API 확인

```bash
# 헬스체크
curl -I http://localhost:8001
curl http://localhost:8001/health  # (헬스체크 엔드포인트가 있다면)

# 한글 데이터 확인
curl http://localhost:8001/api/test | grep -o "[가-힣]" | head -5
```

### 프론트엔드 확인

```bash
# 로컬에서 확인
curl -I http://localhost:80

# 원격 브라우저에서 접속
# http://서버IP 로 접속하여 한글 표시 확인
```


---

## 🚨 트러블슈팅

### 1. iconv 명령어가 없는 경우

```bash
# RHEL/CentOS/Rocky Linux
yum install -y glibc-common

# Debian/Ubuntu
apt-get update && apt-get install -y libc-bin
```

### 2. 인코딩 변환 실패 시

```bash
# 특정 파일 수동 확인
file -i /tmp/backend-fix/app/some_file.py

# 수동 변환
iconv -f LATIN1 -t UTF-8 input.file > output.file
```

### 3. MySQL 한글 깨짐이 계속되는 경우

MySQL 설정 확인:

```bash
docker exec ibk_mysql mysql -uroot -proot -e "
  SHOW VARIABLES LIKE 'character_set%';
  SHOW VARIABLES LIKE 'collation%';
"
```

docker-compose.yml에 다음 환경변수 추가:

```yaml
mysql_db:
  environment:
    - MYSQL_ROOT_PASSWORD=root
    - MYSQL_CHARACTER_SET_SERVER=utf8mb4
    - MYSQL_COLLATION_SERVER=utf8mb4_unicode_ci
```

### 4. 컨테이너가 시작되지 않는 경우

```bash
# 개별 컨테이너 로그 확인
docker logs ibk_mysql
docker logs ibk_backend
docker logs ibk_frontend

# 상세 상태 확인
docker inspect ibk_mysql | grep -A 10 "State"
```

---

## 📊 체크리스트

배포 완료 후 다음 항목들을 확인하세요:

- [ ] 모든 컨테이너가 Up 상태
- [ ] MySQL 데이터베이스 접속 가능
- [ ] 백엔드 API 응답 정상
- [ ] 프론트엔드 페이지 로딩 정상
- [ ] **한글 데이터가 깨지지 않고 정상 표시**
- [ ] 로그에 인코딩 관련 에러 없음

---

## 🔄 정리 작업 (선택사항)

배포 완료 후 임시 파일 정리:

```bash
# 임시 디렉토리 삭제
rm -rf /tmp/frontend-fix /tmp/backend-fix /tmp/mysql-fix

# 분할 조각 파일 삭제 (원본 보관)
rm -f *.part-??

# 사용하지 않는 Docker 이미지 정리
docker image prune -f
```

---

## 📝 추가 참고사항

### 인코딩 문제 예방법 (향후)

다음 배포부터는 파일 생성 시 UTF-8 인코딩 사용:

```bash
# 파일 생성 시
export LANG=ko_KR.UTF-8
export LC_ALL=ko_KR.UTF-8

# tar 생성 시
tar --format=posix -cf archive.tar files/
```

### 파일 인코딩 확인 명령어

```bash
# 단일 파일
file -i filename.txt

# 디렉토리 전체
find . -type f -exec file -i {} \; | grep -v utf-8
```

---

**배포 완료! 🎉**

문제 발생 시 위 트러블슈팅 섹션을 참조하거나 로그를 확인하세요.
