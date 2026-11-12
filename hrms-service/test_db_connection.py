import asyncio
from sqlalchemy import text
from app.database.session import get_engine


async def main():
    try:
        async with get_engine().connect() as connection:
            result = await connection.execute(text("SELECT version()"))
            print("DATABASE CONNECTION SUCCESSFUL")
            print(result.scalar())
    except Exception as error:
        print("DATABASE CONNECTION FAILED")
        print(type(error).__name__, str(error))
    finally:
        from app.database.session import dispose_engine
        await dispose_engine()


asyncio.run(main())