# 🛠️ Installation Guide

This guide provides step-by-step instructions to set up and run the **University Exam Timetabling System (UETP)** on your local machine from scratch.

## 📋 Prerequisites

Before you begin, ensure you have the following installed on your system:
* **[Python 3.10+](https://www.python.org/downloads/)** (Required for the backend API and CP-SAT solver)
* **[Node.js 18+](https://nodejs.org/)** (Required for the frontend and package management)
* **Git** (To clone the repository)

---

## 🚀 Step 1: Clone the Repository

Open your terminal (or Command Prompt) and clone the project repository:

```bash
git clone https://github.com/e-cagan/csp-exam-timetabling.git
cd csp-exam-timetabling
```

---

## 🐍 Step 2: Backend (API) Setup

To set up the AI solver (Google OR-Tools) and the FastAPI backend, follow these steps in the root directory of the project.

1. **(Optional but Recommended) Create a Virtual Environment:**
   It's best practice to use a virtual environment (`venv`) to avoid dependency conflicts:
   ```bash
   python -m venv venv
   
   # To activate on Windows:
   venv\Scripts\activate
   
   # To activate on macOS/Linux:
   source venv/bin/activate
   ```

2. **Install Required Python Packages:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the FastAPI Server:**
   ```bash
   python api.py
   ```
   *Once started successfully, the backend will be running at `http://127.0.0.1:8000`. Keep this terminal window open.*

---

## 💻 Step 3: Frontend (UI) Setup

Open a **new** terminal window (or tab) and follow these steps:

1. **Navigate to the Frontend Directory:**
   ```bash
   cd frontend
   ```

2. **Install Node Dependencies (⚠️ IMPORTANT):**
   > **Note:** Due to strict peer dependency conflicts with the Tailwind CSS version used in this project, running a standard `npm install` might throw an error. To ensure a smooth installation, you **must** use the following command to bypass these conflicts:
   
   ```bash
   npm install --legacy-peer-deps
   ```

3. **Start the Development Server (Vite):**
   ```bash
   npm run dev
   ```

---

## 🎉 Step 4: Start Using the System!

With both the Backend and Frontend servers running, open your web browser and navigate to:

👉 **`http://localhost:5173`**

*(Note: When running locally, the frontend is automatically configured to send API requests to your local backend at `http://localhost:8000`. No extra environment variable configuration is needed.)*