const databaseName = process.env.MONGODB_DATABASE || "brseai";
const appUsername = process.env.MONGODB_APP_USERNAME;
const appPassword = process.env.MONGODB_APP_PASSWORD;

if (!appUsername || !appPassword) {
  throw new Error(
    "MONGODB_APP_USERNAME and MONGODB_APP_PASSWORD are required to initialize the MongoDB app user",
  );
}

const appDb = db.getSiblingDB(databaseName);
const roles = [{ role: "readWrite", db: databaseName }];

if (appDb.getUser(appUsername)) {
  appDb.updateUser(appUsername, {
    pwd: appPassword,
    roles,
  });
  print(`Updated MongoDB app user ${appUsername} for database ${databaseName}`);
} else {
  appDb.createUser({
    user: appUsername,
    pwd: appPassword,
    roles,
  });
  print(`Created MongoDB app user ${appUsername} for database ${databaseName}`);
}
